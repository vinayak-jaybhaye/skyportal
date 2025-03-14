from skyportal.tests import api, assert_api, assert_api_fail


def test_add_and_retrieve_annotation_group_id(
    annotation_token, upload_data_token, public_source, public_group, ztf_camera
):
    status, data = api(
        "POST",
        "photometry",
        data={
            "obj_id": str(public_source.id),
            "mjd": 58000.0,
            "instrument_id": ztf_camera.id,
            "flux": 12.24,
            "fluxerr": 0.031,
            "zp": 25.0,
            "magsys": "ab",
            "filter": "ztfg",
            "group_ids": [public_group.id],
            "altdata": {"some_key": "some_value"},
        },
        token=upload_data_token,
    )
    assert_api(status, data)

    photometry_id = data["data"]["ids"][0]

    # try posting without an origin...
    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "photometry_id": photometry_id,
            "data": {"offset_from_host_galaxy": 1.5},
            "group_ids": [public_group.id],
        },
        token=annotation_token,
    )
    assert_api_fail(status, data, 400, "origin must be specified")

    # this should not work, since "origin" is empty
    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "",
            "data": {"offset_from_host_galaxy": 1.5},
            "group_ids": [public_group.id],
        },
        token=annotation_token,
    )

    assert status in [400, 401]
    assert "Input `origin` must begin with alphanumeric/underscore" in data["message"]

    # first time adding an annotation to this object from Kowalski
    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "kowalski",
            "data": {"offset_from_host_galaxy": 1.5},
            "group_ids": [public_group.id],
        },
        token=annotation_token,
    )

    assert status == 200
    annotation_id = data["data"]["annotation_id"]

    # this should not work, since "origin" Kowalski was already posted to this object
    # instead, try updating the existing annotation if you have new information!
    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "kowalski",
            "data": {"offset_from_host_galaxy": 1.5},
            "group_ids": [public_group.id],
        },
        token=annotation_token,
    )

    assert status in [500, 400]
    assert "duplicate key value violates unique constraint" in data["message"]

    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )

    assert status == 200
    assert data["data"]["data"]["offset_from_host_galaxy"] == 1.5


def test_add_and_retrieve_annotation_group_access(
    annotation_token_two_groups,
    upload_data_token_two_groups,
    public_source_two_groups,
    public_group2,
    public_group,
    annotation_token,
    ztf_camera,
):
    status, data = api(
        "POST",
        "photometry",
        data={
            "obj_id": str(public_source_two_groups.id),
            "mjd": 58000.0,
            "instrument_id": ztf_camera.id,
            "flux": 12.24,
            "fluxerr": 0.031,
            "zp": 25.0,
            "magsys": "ab",
            "filter": "ztfg",
            "group_ids": [public_group2.id],
            "altdata": {"some_key": "some_value"},
        },
        token=upload_data_token_two_groups,
    )
    assert_api(status, data)

    photometry_id = data["data"]["ids"][0]

    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "IPAC",
            "photometry_id": photometry_id,
            "data": {"distance_from_host": 7.4},
            "group_ids": [public_group2.id],
        },
        token=annotation_token_two_groups,
    )
    assert status == 200
    annotation_id = data["data"]["annotation_id"]

    # This token belongs to public_group2
    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token_two_groups,
    )
    assert status == 200
    assert data["data"]["data"]["distance_from_host"] == 7.4

    # This token does not belong to public_group2
    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 403

    # Both tokens should be able to view this annotation, but not the underlying photometry
    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "kowalski",
            "photometry_id": photometry_id,
            "data": {"ACAI_class": "type Ia"},
            "group_ids": [public_group.id, public_group2.id],
        },
        token=annotation_token_two_groups,
    )
    assert status == 200
    annotation_id = data["data"]["annotation_id"]

    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token_two_groups,
    )
    assert status == 200
    assert data["data"]["data"]["ACAI_class"] == "type Ia"

    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 403  # the underlying photometry is not accessible to group1

    # post new photometry with an annotation, open to both groups
    status, data = api(
        "POST",
        "photometry",
        data={
            "obj_id": str(public_source_two_groups.id),
            "mjd": 58001.0,
            "instrument_id": ztf_camera.id,
            "flux": 12.24,
            "fluxerr": 0.031,
            "zp": 25.0,
            "magsys": "ab",
            "filter": "ztfg",
            "group_ids": [public_group.id, public_group2.id],
            "altdata": {"some_key": "some_value"},
        },
        token=upload_data_token_two_groups,
    )
    assert_api(status, data)

    photometry_id = data["data"]["ids"][0]

    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "kowalski",
            "photometry_id": photometry_id,
            "data": {"ACAI_class": "type Ia"},
            "group_ids": [public_group2.id],
        },
        token=annotation_token_two_groups,
    )
    assert status == 200
    annotation_id = data["data"]["annotation_id"]

    # token for group1 can view the photometry but cannot see the annotation
    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 403

    # Both tokens should be able to view annotation after updating group list
    status, data = api(
        "PUT",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        data={
            "data": {"ACAI_class": "type IIn"},
            "group_ids": [public_group.id, public_group2.id],
        },
        token=annotation_token_two_groups,
    )
    assert status == 200

    # the new annotation on the new photometry should now accessible
    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 200
    assert data["data"]["data"]["ACAI_class"] == "type IIn"


def test_cannot_add_annotation_without_permission(
    view_only_token, upload_data_token, public_source, ztf_camera
):
    status, data = api(
        "POST",
        "photometry",
        data={
            "obj_id": str(public_source.id),
            "mjd": 58000.0,
            "instrument_id": ztf_camera.id,
            "flux": 12.24,
            "fluxerr": 0.031,
            "zp": 25.0,
            "magsys": "ab",
            "filter": "ztfg",
            "group_ids": "all",
            "altdata": {"some_key": "some_value"},
        },
        token=upload_data_token,
    )
    assert_api(status, data)

    photometry_id = data["data"]["ids"][0]

    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotation",
        data={"origin": "kowalski", "data": {"gaia_G": 14.5}},
        token=view_only_token,
    )
    assert status in [401, 405]
    assert data["status"] == "error"


def test_delete_annotation(
    annotation_token, upload_data_token, public_source, ztf_camera
):
    status, data = api(
        "POST",
        "photometry",
        data={
            "obj_id": str(public_source.id),
            "mjd": 58000.0,
            "instrument_id": ztf_camera.id,
            "flux": 12.24,
            "fluxerr": 0.031,
            "zp": 25.0,
            "magsys": "ab",
            "filter": "ztfg",
            "group_ids": "all",
            "altdata": {"some_key": "some_value"},
        },
        token=upload_data_token,
    )
    assert_api(status, data)

    photometry_id = data["data"]["ids"][0]

    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={"origin": "kowalski", "data": {"gaia_G": 14.5}},
        token=annotation_token,
    )
    assert status == 200
    annotation_id = data["data"]["annotation_id"]

    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 200
    assert data["data"]["data"]["gaia_G"] == 14.5

    # try to delete using the wrong photometry ID
    status, data = api(
        "DELETE",
        f"photometry/{photometry_id + 1}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 400
    assert (
        "Annotation resource ID does not match resource ID given in path"
        in data["message"]
    )

    status, data = api(
        "DELETE",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 200

    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations/{annotation_id}",
        token=annotation_token,
    )
    assert status == 403


def test_fetch_all_photometry_annotations(
    annotation_token, upload_data_token, public_source, public_group, ztf_camera
):
    status, data = api(
        "POST",
        "photometry",
        data={
            "obj_id": str(public_source.id),
            "mjd": 58000.0,
            "instrument_id": ztf_camera.id,
            "flux": 12.24,
            "fluxerr": 0.031,
            "zp": 25.0,
            "magsys": "ab",
            "filter": "ztfg",
            "group_ids": "all",
            "altdata": {"some_key": "some_value"},
        },
        token=upload_data_token,
    )
    assert_api(status, data)

    photometry_id = data["data"]["ids"][0]

    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "kowalski",
            "data": {"gaia_G": 15.7},
            "group_ids": [public_group.id],
        },
        token=annotation_token,
    )
    assert status == 200

    status, data = api(
        "POST",
        f"photometry/{photometry_id}/annotations",
        data={
            "origin": "SEDM",
            "data": {"redshift": 0.07},
            "group_ids": [public_group.id],
        },
        token=annotation_token,
    )
    assert status == 200

    status, data = api(
        "GET",
        f"photometry/{photometry_id}/annotations",
        token=upload_data_token,
    )

    # make sure the dictionaries are sorted
    data["data"] = sorted(data["data"], key=lambda x: x["origin"])

    assert status == 200
    assert len(data["data"]) == 2
    assert data["data"][0]["data"]["redshift"] == 0.07
    assert data["data"][1]["data"]["gaia_G"] == 15.7
