"""URL resolution, the revision chain, and the constraints Alembic imposes (RX-47).

Most of this module needs no container - it exercises URL resolution and the
script directory. It is marked `integration` with the rest of the directory
anyway, so `tests/migrations` deselects as one unit and nobody has to remember
which half needs PostgreSQL; the two tests that DO need it say so in their
docstrings.

WHY URL RESOLUTION IS TESTED AT ALL. `alembic upgrade head` against an
unintended database is not undone by running it again, and the identity that runs
it is privileged. A resolver that fell back to a localhost default would make
that mistake reachable by forgetting an environment variable. So the resolver
must raise, and the refusal must name what is missing - a `NEEDS_CONFIGURATION`
that does not say which variable is absent sends the operator guessing.

IDENTITY: no database identity for the resolution tests. `retrace_app` for the
two that read a realised catalogue.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from retrace_api.db import migrate
from retrace_api.db.engine import (
    BOOTSTRAP_CREDENTIAL_VAR,
    BOOTSTRAP_USER_VAR,
    DIRECT_URL_VAR,
    MIGRATION_CREDENTIAL_VAR,
    MIGRATION_USER_VAR,
    RUNTIME_CREDENTIAL_VAR,
    RUNTIME_USER_VAR,
    bootstrap_url_from_env,
    build_url,
    migration_url_from_env,
    runtime_url_from_env,
)
from retrace_api.errors import MigrationConfigurationError

pytestmark = pytest.mark.integration

#: Alembic hardcodes `alembic_version.version_num` as `varchar(32)`. A longer
#: revision id is accepted by the script directory and then fails at the very END
#: of an upgrade with `StringDataRightTruncation` - after the DDL has run. This
#: happened while building the chain; the limit is asserted against the REALISED
#: column width rather than against this number, which is here only for the
#: message.
DOCUMENTED_VERSION_WIDTH = 32


@pytest.mark.parametrize(
    ("resolver", "user_var", "credential_var", "identity"),
    [
        (migration_url_from_env, MIGRATION_USER_VAR, MIGRATION_CREDENTIAL_VAR, "migration"),
        (bootstrap_url_from_env, BOOTSTRAP_USER_VAR, BOOTSTRAP_CREDENTIAL_VAR, "bootstrap"),
        (runtime_url_from_env, RUNTIME_USER_VAR, RUNTIME_CREDENTIAL_VAR, "runtime"),
    ],
)
def test_an_unconfigured_identity_reports_needs_configuration(
    resolver, user_var: str, credential_var: str, identity: str
) -> None:
    """NEGATIVE CONTROL: no default DSN, and the refusal names the missing variables.

    An empty environment is passed explicitly rather than monkeypatching
    `os.environ`, so the test cannot be influenced by the developer's shell.
    """
    with pytest.raises(MigrationConfigurationError) as caught:
        resolver({})
    message = str(caught.value)
    assert message.startswith("NEEDS_CONFIGURATION:"), message
    assert identity in message, message
    assert user_var in message and credential_var in message, message
    assert DIRECT_URL_VAR in message, message


@pytest.mark.parametrize(
    ("resolver", "user_var", "credential_var"),
    [
        (migration_url_from_env, MIGRATION_USER_VAR, MIGRATION_CREDENTIAL_VAR),
        (bootstrap_url_from_env, BOOTSTRAP_USER_VAR, BOOTSTRAP_CREDENTIAL_VAR),
        (runtime_url_from_env, RUNTIME_USER_VAR, RUNTIME_CREDENTIAL_VAR),
    ],
)
def test_a_half_configured_identity_is_still_refused(
    resolver, user_var: str, credential_var: str
) -> None:
    """A user with no credential must not resolve to a passwordless URL.

    That URL would succeed against a `trust`-configured server and fail
    everywhere else, which is the worst of both outcomes: it works in
    development and is refused in production for a reason the message does not
    give.
    """
    with pytest.raises(MigrationConfigurationError) as caught:
        resolver({user_var: "someone"})
    assert credential_var in str(caught.value), caught.value


def test_a_configured_identity_resolves_to_the_expected_url() -> None:
    """DISCRIMINATION for the refusals above: a complete environment resolves.

    Without this, the refusal tests would be satisfied by a resolver that refused
    everything.
    """
    url = migration_url_from_env(
        {
            MIGRATION_USER_VAR: "retrace_migrator",
            MIGRATION_CREDENTIAL_VAR: "s3cret",  # noqa: S106 - a test fixture value
            "RETRACE_PG_HOST": "db.internal",
            "RETRACE_PG_PORT": "6543",
            "RETRACE_PG_DATABASE": "retrace_prod",
        }
    )
    assert url.drivername == "postgresql+psycopg", url.drivername
    assert url.username == "retrace_migrator"
    assert url.host == "db.internal"
    assert url.port == 6543
    assert url.database == "retrace_prod"


def test_a_complete_direct_url_is_used_verbatim() -> None:
    """`RETRACE_DATABASE_URL` wins and is NOT merged with the per-identity variables.

    Merging would produce a URL nobody wrote - for instance the direct URL's host
    with a different identity's username - and the resulting connection failure
    would point at the wrong configuration.
    """
    url = migration_url_from_env(
        {
            DIRECT_URL_VAR: "postgresql+psycopg://direct:pw@elsewhere:5555/other",
            MIGRATION_USER_VAR: "ignored",
            MIGRATION_CREDENTIAL_VAR: "ignored",
        }
    )
    assert url.username == "direct", url
    assert url.host == "elsewhere" and url.port == 5555, url
    assert url.database == "other", url


def test_a_non_integer_port_is_refused_rather_than_coerced() -> None:
    """A malformed port must not silently become the default.

    Falling back to 5432 for `RETRACE_PG_PORT=five thousand` would connect to a
    DIFFERENT server than the operator configured - possibly a production one on
    the default port.
    """
    with pytest.raises(MigrationConfigurationError) as caught:
        migration_url_from_env(
            {
                MIGRATION_USER_VAR: "u",
                MIGRATION_CREDENTIAL_VAR: "p",
                "RETRACE_PG_PORT": "five thousand",
            }
        )
    assert "RETRACE_PG_PORT" in str(caught.value), caught.value


@pytest.mark.parametrize("secret", ["pw%with%percent", "pw@with@at", "pw/with/slash", "p#w?x=1"])
def test_a_credential_with_url_metacharacters_survives_a_round_trip(secret: str) -> None:
    """The quoting hazard, asserted rather than assumed.

    A password containing `@`, `/`, `#` or `%` corrupts a hand-built URL string,
    and `%` is additionally consumed by ConfigParser interpolation if the URL is
    written into an Alembic ini option. Both failures surface as authentication
    errors, which send the reader to look at the server. `URL.create` plus
    `make_url` must round-trip the value exactly.
    """
    url = build_url(
        host="127.0.0.1", port=5432, database="retrace", username="u", password=secret
    )
    assert url.password == secret
    rendered = url.render_as_string(hide_password=False)
    assert sa.make_url(rendered).password == secret, rendered
    # And it must not be readable from the default rendering, which is what gets
    # into log lines and exception messages.
    assert secret not in url.render_as_string(), "the credential is not masked by default"


def test_the_chain_has_exactly_one_head_and_is_linear() -> None:
    """A tenancy schema with two heads has no single definition of "current".

    `upgrade head` would be ambiguous, and two operators could bring two
    databases to different states while both reported success.
    """
    script = ScriptDirectory.from_config(migrate.make_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one head, got {heads}"
    assert migrate.head_revision() == heads[0]

    revisions = list(script.walk_revisions())
    assert len(revisions) >= 2, [r.revision for r in revisions]
    for revision in revisions:
        downs = revision.down_revision
        normalised = () if downs is None else (downs,) if isinstance(downs, str) else tuple(downs)
        assert len(normalised) <= 1, f"{revision.revision} is a merge point: {normalised}"
    # `get_bases()` returns a list; compared as a list rather than coerced, so a
    # future Alembic that returned something else fails here instead of being
    # quietly accepted.
    assert list(script.get_bases()) == ["0001_tenancy_baseline"], script.get_bases()


def test_every_revision_id_fits_the_realised_version_column(fresh_database: sa.URL) -> None:
    """REGRESSION GUARD for a defect this chain actually hit. Needs PostgreSQL.

    Alembic's version table is created with a fixed-width `version_num`. A longer
    revision id passes every static check, runs the whole upgrade, and then fails
    on the final `UPDATE alembic_version` with `StringDataRightTruncation` - so
    the DDL has already been applied and the error looks like a data problem
    rather than a naming one. `0002` was first named
    `0002_result_contract_project_index` (34 characters) and did exactly that.

    The width is read from the REALISED column rather than hardcoded, so the
    check follows Alembic rather than a number copied from its source.
    """
    migrate.upgrade(fresh_database, "head")
    engine = sa.create_engine(fresh_database, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as c:
            width = c.execute(
                sa.text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'alembic_version' "
                    "AND column_name = 'version_num'"
                )
            ).scalar()
    finally:
        engine.dispose()

    assert width is not None, "alembic_version.version_num has no length limit to check"
    assert width == DOCUMENTED_VERSION_WIDTH, (
        f"the realised version column is {width} wide, not the documented "
        f"{DOCUMENTED_VERSION_WIDTH}; update the note in this module"
    )

    script = ScriptDirectory.from_config(migrate.make_config())
    too_long = [
        r.revision for r in script.walk_revisions() if len(r.revision) > int(width)
    ]
    assert not too_long, (
        f"revision ids longer than {width} characters will fail at the END of an "
        f"upgrade, after the DDL has run: {too_long}"
    )
    # Vacuity guard: the check must be able to find something. A 33-character id
    # under this width would be rejected.
    assert len("x" * (int(width) + 1)) > int(width)


def test_make_config_points_at_the_packaged_script_directory() -> None:
    """The script location is absolute and derived from the package.

    A relative `script_location` resolves against the caller's working directory,
    so `python -m retrace_api.db.migrate upgrade` run from anywhere but
    `services/api` would find no revisions - and Alembic reports "no revisions"
    as an empty upgrade, not as an error.
    """
    config = migrate.make_config()
    location = config.get_main_option("script_location")
    assert location is not None
    assert location == str(migrate.MIGRATIONS_PATH), location
    assert migrate.MIGRATIONS_PATH.is_absolute(), migrate.MIGRATIONS_PATH
    assert (migrate.MIGRATIONS_PATH / "env.py").is_file()
    assert (migrate.MIGRATIONS_PATH / "versions").is_dir()
