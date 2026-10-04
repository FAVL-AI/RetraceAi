"""Upload admission, through the real route (RX-01, RX-42).

SIX REFUSALS AND ONE ADMISSION, AND THE ADMISSION IS THE POINT.

RX-42 names a zip bomb, a path-traversing archive, a macro-bearing document and
a pickle payload. Each is refused below, together with a content-type/sniff
disagreement and an oversize upload. A suite of refusals alone cannot tell a
working gate from a route that refuses everything, so the legitimate
notebook-plus-CSV archive is admitted AND promoted to a content-addressed
snapshot in the same file - and the standalone notebook case is admitted too,
because that is the one a prefix-only sniff used to refuse.

THE REFUSALS ARE IDENTIFIED BY REASON, NOT BY STATUS.

``extra.reason`` names the rule that refused the payload, so a test asserts the
intended rule fired rather than that *something* did. A bomb refused as a
filename error would pass a status-only assertion while proving nothing about
the bomb.

NOTHING HERE DESERIALISES A PAYLOAD.

The pickle fixtures are literal opcode prefixes written as bytes. ``pickle`` is
not imported by this file or by the module under test, so there is no path on
which a fixture could execute.
"""

from __future__ import annotations

import io
import json
import pathlib
import zipfile

import pytest
from api_support import (
    CSV_BYTES,
    MEMBER,
    TENANT_A,
    Harness,
    legitimate_archive,
    notebook_bytes,
)
from retrace_api.web.admission import (
    ADMITTED_ARCHIVE_SUFFIXES,
    NOTEBOOK_MARKER,
    OLE2_MAGIC,
    PICKLE_MAGIC,
    AdmissionPolicy,
    DetectedKind,
    admit_bytes,
    sniff,
)
from retrace_api.web.errors import UploadRefused
from retrace_verifier import REFUSED_MAGIC

#: The policy the harness wires. Restated so the pure-function tests use the
#: same ceilings as the route tests.
POLICY = AdmissionPolicy(
    max_upload_bytes=4096,
    max_archive_members=16,
    max_archive_member_bytes=2048,
    max_archive_total_bytes=8192,
    max_compression_ratio=20.0,
)


def refusal_reason(response) -> str:
    """The admission rule a refused response names."""
    return str(response.json()["error"]["context"]["reason"])


def archive_of(members: dict[str, bytes], *, compress: bool = True) -> bytes:
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", method) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def archive_with_rewritten_member_size() -> bytes:
    """An archive whose metadata declares a far smaller member than it carries.

    Both size fields - the local header's and the central directory's - are
    rewritten, which is what an attacker controls. Nothing here is a mock: the
    bytes are a real zip file that real readers disagree with.
    """
    payload = b"y" * 5000
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.csv", payload)
    raw = buffer.getvalue()
    true_size = len(payload).to_bytes(4, "little")
    assert raw.count(true_size) >= 2, "the fixture must find both size fields to rewrite"
    return raw.replace(true_size, (10).to_bytes(4, "little"))


# --------------------------------------------------------------------------- #
# The admission, first: every refusal below is measured against this.
# --------------------------------------------------------------------------- #


def test_a_notebook_and_a_csv_in_an_archive_are_admitted(harness: Harness) -> None:
    """RX-42: the discriminating case. A gate that refuses this is not a gate."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="study.zip",
        content_type="application/zip",
        data=legitimate_archive(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["admitted"] is True
    assert body["detected_kind"] == "ZIP_ARCHIVE"
    assert body["member_count"] == 2
    assert body["sha256"]


def test_an_admitted_archive_promotes_to_a_content_addressed_snapshot(
    harness: Harness,
) -> None:
    """RX-01: admission is only useful if the admitted bytes can be pinned."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    upload = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="study.zip",
        content_type="application/zip",
        data=legitimate_archive(),
    )
    upload_id = upload.json()["upload_id"]
    snapshot = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/snapshots",
        json={"upload_id": upload_id},
        headers=harness.headers(MEMBER),
    )
    assert snapshot.status_code == 201, snapshot.text
    body = snapshot.json()
    assert body["file_count"] == 2
    assert sorted(body["files"]) == ["analysis.ipynb", "data/penguins.csv"]
    assert len(body["manifest_digest"]) == 64


def test_a_real_notebook_declared_as_a_notebook_is_admitted(harness: Harness) -> None:
    """RX-42: the case a prefix-only sniff refused.

    Every notebook writer emits ``nbformat`` after ``cells``, so in a real
    notebook the key sits far past the sniff prefix. Looking for it only in the
    first 512 bytes classified the document as plain ``JSON``, which
    ``application/x-ipynb+json`` does not admit - so a correctly declared,
    entirely legitimate notebook was refused as a content-type mismatch.
    """
    data = notebook_bytes(cells=8)
    assert NOTEBOOK_MARKER not in data[:512], (
        "the fixture must put the marker beyond the sniff prefix, or this test "
        "would pass for the wrong reason"
    )
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="analysis.ipynb",
        content_type="application/x-ipynb+json",
        data=data,
    )
    assert response.status_code == 201, response.text
    assert response.json()["detected_kind"] == "NOTEBOOK"


def test_json_that_is_not_a_notebook_declared_as_one_is_refused(harness: Harness) -> None:
    """NEGATIVE CONTROL: the wider marker search did not make the type check vacuous."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="results.ipynb",
        content_type="application/x-ipynb+json",
        data=json.dumps({"results": [1, 2, 3]}).encode("utf-8"),
    )
    assert response.status_code == 415
    assert refusal_reason(response) == "content-type-mismatch"


def test_a_csv_declared_as_a_csv_is_admitted(harness: Harness) -> None:
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="penguins.csv",
        content_type="text/csv",
        data=CSV_BYTES,
    )
    assert response.status_code == 201, response.text
    assert response.json()["detected_kind"] == "CSV"


# --------------------------------------------------------------------------- #
# Zip slip.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "member",
    ["../escaped.csv", "data/../../escaped.csv", "/etc/escaped.csv", "..\\escaped.csv"],
)
def test_a_traversing_archive_member_is_refused(harness: Harness, member: str) -> None:
    """RX-42, T7: zip slip, in each of the forms that reach the same write."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="slip.zip",
        content_type="application/zip",
        data=archive_of({member: CSV_BYTES}),
    )
    assert response.status_code == 422, response.text
    assert refusal_reason(response) == "archive-member-traversal"


def test_a_symlink_member_is_refused(harness: Harness) -> None:
    """A symlink would redirect a later write outside the extraction root."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        info = zipfile.ZipInfo("link.csv")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "../../elsewhere.csv")
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="link.zip",
        content_type="application/zip",
        data=buffer.getvalue(),
    )
    assert response.status_code == 422
    assert refusal_reason(response) == "archive-non-regular-member"


def test_no_file_is_written_outside_the_workspace_when_a_slip_is_refused(
    harness: Harness, tmp_path: pathlib.Path
) -> None:
    """The refusal has to leave nothing behind, not merely report a problem."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="slip.zip",
        content_type="application/zip",
        data=archive_of({"../escaped.csv": CSV_BYTES}),
    )
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    created = after - before
    # The quarantined payload and the index record are expected; an `escaped.csv`
    # anywhere is not.
    assert not [p for p in created if p.name == "escaped.csv"]
    assert all(
        p.name.endswith((".bin", ".jsonl")) or p.parent.name == "objects"
        for p in created
    ), sorted(str(p) for p in created)


# --------------------------------------------------------------------------- #
# Decompression bombs: three independent limits.
# --------------------------------------------------------------------------- #


def test_a_high_ratio_archive_is_refused(harness: Harness) -> None:
    """RX-42: the compression-ratio cap, with a payload that defeats the others."""
    bomb = archive_of({"zeros.csv": b"0" * 60_000})
    assert len(bomb) < POLICY.max_upload_bytes, "the bomb must not trip the size cap first"
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="bomb.zip",
        content_type="application/zip",
        data=bomb,
    )
    assert response.status_code == 413, response.text
    assert refusal_reason(response) in {
        "archive-member-too-large",
        "archive-compression-ratio",
    }


def test_the_ratio_cap_and_the_member_cap_are_not_the_same_check() -> None:
    """Each limit is shown to fire on a payload the other admits (RX-42).

    A single assertion on "a bomb is refused" cannot distinguish four limits
    from one, and a bomb defeats any three of them alone.
    """
    # Small members, enormous ratio: under every size cap, over the ratio cap.
    ratio_only = archive_of({"a.csv": b"0" * 1800})
    with pytest.raises(UploadRefused) as refusal:
        admit_bytes(
            ratio_only, filename="a.zip", declared_content_type="application/zip", policy=POLICY
        )
    assert refusal.value.extra["reason"] == "archive-compression-ratio"

    # One oversized member, stored uncompressed: ratio 1.0, over the member cap.
    member_only = archive_of({"a.csv": b"x" * 2100}, compress=False)
    with pytest.raises(UploadRefused) as refusal:
        admit_bytes(
            member_only,
            filename="a.zip",
            declared_content_type="application/zip",
            policy=AdmissionPolicy(
                max_upload_bytes=1024 * 1024,
                max_archive_members=16,
                max_archive_member_bytes=2048,
                max_archive_total_bytes=8192,
                max_compression_ratio=20.0,
            ),
        )
    assert refusal.value.extra["reason"] == "archive-member-too-large"

    # Many members, each tiny and incompressible: under the ratio and member
    # caps, over the member-count cap.
    count_only = archive_of(
        {f"m{index}.csv": f"{index},x\n".encode() for index in range(20)}, compress=False
    )
    with pytest.raises(UploadRefused) as refusal:
        admit_bytes(
            count_only,
            filename="a.zip",
            declared_content_type="application/zip",
            policy=AdmissionPolicy(
                max_upload_bytes=1024 * 1024,
                max_archive_members=16,
                max_archive_member_bytes=2048,
                max_archive_total_bytes=8192,
                max_compression_ratio=20.0,
            ),
        )
    assert refusal.value.extra["reason"] == "archive-member-count"


def test_a_member_whose_data_contradicts_its_metadata_is_refused_not_a_server_fault(
    harness: Harness,
) -> None:
    """RX-42: a crafted archive is a REFUSAL, never a 500.

    The archive declares a 10-byte member and carries 5000 bytes of deflate
    data. CPython's reader stops at the declared size and then fails the
    member's own CRC check, raising ``zipfile.BadZipFile`` from inside the prefix
    read admission performs. Uncaught, that is an unhandled exception: a crafted
    payload turning into a server fault, which is both a wrong answer and an
    availability finding.
    """
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="crafted.zip",
        content_type="application/zip",
        data=archive_with_rewritten_member_size(),
    )
    assert response.status_code == 422, response.text
    assert refusal_reason(response) == "archive-member-unreadable"


def test_the_same_crafted_archive_is_refused_at_promotion_too(
    harness: Harness, tmp_path: pathlib.Path
) -> None:
    """Both layers refuse it, and the promotion layer leaves no partial file.

    Promotion is reached directly here because admission already refuses the
    payload over the route, so the route cannot exercise this path. Calling the
    promotion function is the only way to show it is not the one place a crafted
    archive would become a 500.
    """
    import datetime as dt

    from retrace_api.web.admission import AdmittedUpload, QuarantinedUpload
    from retrace_api.web.promotion import materialise_admitted

    raw = archive_with_rewritten_member_size()
    destination = tmp_path / "staging"
    quarantined = QuarantinedUpload(
        upload_id="u1",
        tenant_id=TENANT_A,
        project_id="p1",
        filename="crafted.zip",
        declared_content_type="application/zip",
        byte_count=len(raw),
        sha256="0" * 64,
        path=tmp_path / "u1.bin",
        received_at=dt.datetime(2026, 10, 4, tzinfo=dt.UTC),
    )
    admitted = AdmittedUpload(
        quarantined=quarantined,
        detected_kind=DetectedKind.ZIP_ARCHIVE,
        member_paths=("big.csv",),
    )
    with pytest.raises(UploadRefused) as refusal:
        materialise_admitted(admitted, raw, destination, policy=POLICY)
    assert refusal.value.extra["reason"] == "archive-member-unreadable"
    assert not (destination / "big.csv").exists()


def test_an_intact_archive_promotes_so_the_crafted_refusals_are_discriminating(
    harness: Harness, tmp_path: pathlib.Path
) -> None:
    """POSITIVE CONTROL for both refusals above, through the same function."""
    import datetime as dt

    from retrace_api.web.admission import AdmittedUpload, QuarantinedUpload
    from retrace_api.web.promotion import materialise_admitted

    raw = archive_of({"small.csv": CSV_BYTES}, compress=False)
    destination = tmp_path / "staging-ok"
    admitted = AdmittedUpload(
        quarantined=QuarantinedUpload(
            upload_id="u2",
            tenant_id=TENANT_A,
            project_id="p1",
            filename="ok.zip",
            declared_content_type="application/zip",
            byte_count=len(raw),
            sha256="0" * 64,
            path=tmp_path / "u2.bin",
            received_at=dt.datetime(2026, 10, 4, tzinfo=dt.UTC),
        ),
        detected_kind=DetectedKind.ZIP_ARCHIVE,
        member_paths=("small.csv",),
    )
    written = materialise_admitted(admitted, raw, destination, policy=POLICY)
    assert written == ("small.csv",)
    assert (destination / "small.csv").read_bytes() == CSV_BYTES


# --------------------------------------------------------------------------- #
# Pickle.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("signature", PICKLE_MAGIC)
def test_a_pickle_payload_is_refused_by_signature(harness: Harness, signature: bytes) -> None:
    """RX-42, RX-10: refused by opcode prefix, never deserialised to find out."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="model.json",
        content_type="application/json",
        data=signature + b"payload-that-is-never-loaded",
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "pickle-stream"


def test_a_pickle_hiding_behind_an_admitted_extension_inside_an_archive_is_refused(
    harness: Harness,
) -> None:
    """The member allowlist is by extension, so the bytes are inspected as well."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="study.zip",
        content_type="application/zip",
        data=archive_of({"data.csv": b"\x80\x04" + b"not-a-csv"}),
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "pickle-stream"


def test_every_pickle_signature_the_verifier_refuses_is_covered_here() -> None:
    """The anti-drift assertion ``admission.py`` points at (RX-10, RX-42).

    The two modules hold their own signature lists because the verifier refuses
    archives outright and this surface must admit them in order to look inside.
    A signature added to the verifier must therefore fail here rather than
    quietly widen the gap between them.
    """
    verifier_pickles = {
        signature for signature, label in REFUSED_MAGIC if "pickle" in label.lower()
    }
    assert verifier_pickles, "the label filter found nothing; the check would be vacuous"
    missing = sorted(sig for sig in verifier_pickles if sig not in PICKLE_MAGIC)
    assert not missing, f"PICKLE_MAGIC does not cover {missing}"


def test_the_coverage_check_detects_a_missing_signature() -> None:
    """DISCRIMINATION CONTROL for the assertion above."""
    pretend_verifier = {b"\x80\x06", *PICKLE_MAGIC}
    missing = sorted(sig for sig in pretend_verifier if sig not in PICKLE_MAGIC)
    assert missing == [b"\x80\x06"]


# --------------------------------------------------------------------------- #
# Macro-bearing documents.
# --------------------------------------------------------------------------- #


def test_an_ole2_compound_document_is_refused(harness: Harness) -> None:
    """RX-42: refused by signature, because deciding would mean parsing it."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="book.json",
        content_type="application/json",
        data=OLE2_MAGIC + b"\x00" * 64,
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "macro-bearing-document"


def test_a_macro_enabled_extension_is_refused(harness: Harness) -> None:
    """Refused by extension as well as by content, so neither alone is relied on."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="book.xlsm",
        content_type="application/zip",
        data=archive_of({"sheet.csv": CSV_BYTES}),
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "macro-bearing-document"


def test_an_ooxml_container_carrying_a_vba_project_is_refused(harness: Harness) -> None:
    """An OOXML file IS a zip, so the macro lives in a member, not in the magic."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="book.zip",
        content_type="application/zip",
        data=archive_of({"xl/vbaProject.bin": b"macro-bytes", "xl/sheet.csv": CSV_BYTES}),
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "macro-bearing-document"


# --------------------------------------------------------------------------- #
# Declared type against sniffed bytes.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "reason"),
    [
        ("data.csv", "text/csv", b'{"not": "a csv"}', "content-type-mismatch"),
        ("data.json", "application/json", CSV_BYTES, "content-type-mismatch"),
        ("data.zip", "application/zip", CSV_BYTES, "content-type-mismatch"),
        ("data.csv", "text/csv", b"PK\x03\x04rest", "content-type-mismatch"),
        ("data.bin", "application/octet-stream", CSV_BYTES, "declared-type-unsupported"),
    ],
)
def test_a_declared_type_that_disagrees_with_the_bytes_is_refused(
    harness: Harness, filename: str, content_type: str, data: bytes, reason: str
) -> None:
    """RX-42: the declared type and the filename are caller-supplied; bytes decide."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A, MEMBER, project_id, filename=filename, content_type=content_type, data=data
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == reason


# --------------------------------------------------------------------------- #
# Size.
# --------------------------------------------------------------------------- #


def test_an_oversize_upload_is_refused(harness: Harness) -> None:
    """RX-42: the size cap, over the real route."""
    policy = harness.state.admission_policy
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="big.csv",
        content_type="text/csv",
        data=b"a,b\n" + b"1,2\n" * policy.max_upload_bytes,
    )
    assert response.status_code == 413, response.text
    assert refusal_reason(response) == "size-cap-exceeded"


def test_a_payload_of_exactly_the_cap_is_admitted(harness: Harness) -> None:
    """POSITIVE CONTROL: the cap refuses what is over it and nothing else.

    ``read_capped`` reads one byte past the ceiling precisely so that a payload
    of exactly the cap is distinguishable from one truncated at it.
    """
    policy = harness.state.admission_policy
    header = b"a,b\n"
    body = b"1,2\n" * ((policy.max_upload_bytes - len(header)) // 4)
    data = header + body
    assert len(data) <= policy.max_upload_bytes
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A, MEMBER, project_id, filename="exact.csv", content_type="text/csv", data=data
    )
    assert response.status_code == 201, response.text


# --------------------------------------------------------------------------- #
# Shape rules that are not in RX-42's list but are reachable.
# --------------------------------------------------------------------------- #


def test_a_nested_archive_is_refused(harness: Harness) -> None:
    """Refused rather than inspected recursively, which is the smaller rule."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    inner = archive_of({"inner.csv": CSV_BYTES})
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="outer.zip",
        content_type="application/zip",
        data=archive_of({"inner.json": inner}, compress=False),
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "archive-nested-archive"


def test_a_member_with_an_unlisted_extension_is_refused(harness: Harness) -> None:
    """A closed allowlist: an unknown extension is refused, never best-effort."""
    assert ".parquet" not in ADMITTED_ARCHIVE_SUFFIXES
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="study.zip",
        content_type="application/zip",
        data=archive_of({"data.parquet": CSV_BYTES}),
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "archive-member-type-refused"


def test_a_filename_with_a_directory_component_is_refused(harness: Harness) -> None:
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="../escape.csv",
        content_type="text/csv",
        data=CSV_BYTES,
    )
    assert response.status_code == 422, response.text
    assert refusal_reason(response) == "filename-unsafe"


def test_an_empty_payload_is_refused(harness: Harness) -> None:
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A, MEMBER, project_id, filename="empty.csv", content_type="text/csv", data=b""
    )
    assert response.status_code == 422, response.text
    assert refusal_reason(response) == "empty-payload"


def test_a_nul_byte_in_a_declared_text_payload_is_refused(harness: Harness) -> None:
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="data.csv",
        content_type="text/csv",
        data=b"a,b\n1,\x00\n",
    )
    assert response.status_code == 415, response.text
    assert refusal_reason(response) == "nul-byte"


def test_a_utf8_document_split_mid_character_at_the_sniff_boundary_is_admitted() -> None:
    """A fixed-size prefix must not decide validity by where a character lands.

    512 bytes of a valid UTF-8 document can end in the middle of a multi-byte
    character. A strict ``bytes.decode`` of the prefix raised on that and the
    payload was refused as "neither a recognised archive nor valid UTF-8" - a
    legitimate document refused for the position of one character.
    """
    data = ("a,b\n" + "x" * 507 + "é" + ",y\n").encode("utf-8")
    assert len(data) > 512
    with pytest.raises(UnicodeDecodeError):
        data[:512].decode("utf-8")
    assert sniff(data) is DetectedKind.CSV


def test_genuinely_invalid_utf8_is_still_refused() -> None:
    """NEGATIVE CONTROL: the incremental decoder did not make the check vacuous."""
    with pytest.raises(UploadRefused) as refusal:
        sniff(b"\xff\xfe\xfd not text at all")
    assert refusal.value.extra["reason"] == "unrecognised-bytes"


# --------------------------------------------------------------------------- #
# A refused upload is recorded and cannot be promoted.
# --------------------------------------------------------------------------- #


def test_a_refused_upload_cannot_be_promoted_to_a_snapshot(harness: Harness) -> None:
    """RX-42: promotion looks the recorded admission up; it does not re-decide."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    refused = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="slip.zip",
        content_type="application/zip",
        data=archive_of({"../escaped.csv": CSV_BYTES}),
    )
    assert refused.status_code == 422
    workspace = harness.state.workspaces.for_tenant(TENANT_A)
    records = workspace.index("uploads").records()
    assert len(records) == 1
    assert records[0]["admitted"] is False
    assert records[0]["reason"] == "archive-member-traversal"

    promotion = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/snapshots",
        json={"upload_id": records[0]["id"]},
        headers=harness.headers(MEMBER),
    )
    assert promotion.status_code == 422
    assert promotion.json()["error"]["code"] == "UPLOAD_REFUSED"


def test_promotion_refuses_an_upload_record_naming_a_path_outside_the_workspace(
    harness: Harness, tmp_path: pathlib.Path
) -> None:
    """CONTAINED VIOLATION for the path check promotion performs at the read.

    The uploads index is server-written and tenant-scoped, so a record naming
    another tenant's file should be unreachable. This test writes one directly -
    which is the only way to show the guard fires, and the reason a guard that is
    never shown to fire is not evidence.
    """
    outside = tmp_path / "planted.bin"
    outside.write_bytes(CSV_BYTES)
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    workspace = harness.state.workspaces.for_tenant(TENANT_A)
    workspace.index("uploads").append(
        {
            "id": "planted-upload",
            "project_id": project_id,
            "tenant_id": TENANT_A,
            "admitted": True,
            "detected_kind": "CSV",
            "member_paths": [],
            "filename": "planted.csv",
            "declared_content_type": "text/csv",
            "byte_count": len(CSV_BYTES),
            "sha256": "0" * 64,
            "path": str(outside),
            "received_at": "2026-10-04T12:00:00+00:00",
        }
    )
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/snapshots",
        json={"upload_id": "planted-upload"},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 422, response.text
    assert refusal_reason(response) == "quarantine-path-escape"


def test_promotion_refuses_an_upload_record_naming_another_tenant(
    harness: Harness,
) -> None:
    """The same guard, on the recorded tenant rather than the recorded path."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    genuine = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="penguins.csv",
        content_type="text/csv",
        data=CSV_BYTES,
    )
    assert genuine.status_code == 201, genuine.text
    workspace = harness.state.workspaces.for_tenant(TENANT_A)
    original = workspace.index("uploads").latest(genuine.json()["upload_id"])
    assert original is not None
    forged = dict(original)
    forged["tenant_id"] = "99999999-9999-4999-8999-999999999999"
    workspace.index("uploads").append(forged)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/snapshots",
        json={"upload_id": forged["id"]},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 422, response.text
    assert refusal_reason(response) == "upload-tenant-mismatch"


def test_the_genuine_record_promotes_so_the_path_guard_is_discriminating(
    harness: Harness,
) -> None:
    """POSITIVE CONTROL for both guards above."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    genuine = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="penguins.csv",
        content_type="text/csv",
        data=CSV_BYTES,
    )
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/snapshots",
        json={"upload_id": genuine.json()["upload_id"]},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 201, response.text
    assert response.json()["files"] == ["penguins.csv"]


def test_an_upload_into_another_tenants_project_is_not_found(harness: Harness) -> None:
    """RX-47: the project must be in the authorised workspace."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    from api_support import TENANT_B, TENANT_B_MEMBER

    harness.sign_in(TENANT_B_MEMBER)
    response = harness.upload(
        TENANT_B,
        TENANT_B_MEMBER,
        project_id,
        filename="penguins.csv",
        content_type="text/csv",
        data=CSV_BYTES,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
