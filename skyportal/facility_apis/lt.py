import time
from copy import deepcopy
from datetime import datetime, timedelta

import arrow
from astropy import units as u
from astropy.coordinates import SkyCoord
from lxml import etree
from suds import Client

from baselayer.app.env import load_env
from baselayer.app.flow import Flow
from baselayer.log import make_log

from ..utils import http
from . import FollowUpAPI

env, cfg = load_env()

log = make_log("facility_apis/lt")

LT_XML_NS = "http://www.rtml.org/v3.1a"
LT_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
LT_SCHEMA_LOCATION = (
    "http://www.rtml.org/v3.1a http://telescope.livjm.ac.uk/rtml/RTML-nightly.xsd"
)


class LTRequest:
    """An XML structure for LT requests."""

    def _build_prolog(self, request):
        """Payload outline for all LT queue requests.

        Returns
        ----------
        payload: etree.Element
            payload outline for LT requests.
        """

        namespaces = {
            "xsi": LT_XSI_NS,
        }
        schemaLocation = etree.QName(LT_XSI_NS, "schemaLocation")
        timestamp = int(time.time())
        payload = etree.Element(
            "RTML",
            {schemaLocation: LT_SCHEMA_LOCATION},
            xmlns=LT_XML_NS,
            mode="request",
            uid=f"{request.obj.id}-{request.id}-{timestamp}",
            version="3.1a",
            nsmap=namespaces,
        )
        return payload

    def _build_project(self, payload, request):
        """Payload header for all LT queue requests.

        Parameters
        ----------

        payload:
            payload for LT requests.

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        Returns
        ----------
        payload: etree.Element
            payload header for request.
        """

        altdata = request.allocation.altdata

        project = etree.Element("Project", ProjectID=altdata["LT_proposalID"])
        contact = etree.SubElement(project, "Contact")

        etree.SubElement(contact, "Username").text = altdata["username"]
        etree.SubElement(contact, "Name").text = altdata["username"]
        payload.append(project)

    def _build_constraints(self, request):
        """Payload constraints for all LT queue requests.

        Parameters
        ----------

        request: skyportal.models.FollowupRequest
            The request to send to LT.

        Returns
        ----------
        constraints: list of etree.Element
            constraints (airmass, sky, seeing, photometry, date) for request.
        """

        airmass_const = etree.Element(
            "AirmassConstraint", maximum=str(request.payload["maximum_airmass"])
        )

        sky_const = etree.Element("SkyConstraint")
        etree.SubElement(sky_const, "Flux").text = str(
            request.payload["sky_brightness"]
        )
        etree.SubElement(sky_const, "Units").text = "magnitudes/square-arcsecond"

        seeing_const = etree.Element(
            "SeeingConstraint",
            maximum=(str(request.payload["maximum_seeing"])),
            units="arcseconds",
        )

        photom_const = etree.Element("ExtinctionConstraint")
        if "photometric" in request.payload and request.payload["photometric"]:
            etree.SubElement(photom_const, "Clouds").text = "clear"
        else:
            etree.SubElement(photom_const, "Clouds").text = "light"

        date_const = etree.Element("DateTimeConstraint", type="include")

        try:
            start_date = deepcopy(request.payload["start_date"])
            end_date = deepcopy(request.payload["end_date"])

            start_date = arrow.get(start_date).format("YYYY-MM-DDTHH:mm:ss")
            end_date = arrow.get(end_date).format("YYYY-MM-DDTHH:mm:ss")

            start = start_date + "+00:00"
            end = end_date + "+00:00"
            etree.SubElement(date_const, "DateTimeStart", system="UT", value=start)
            etree.SubElement(date_const, "DateTimeEnd", system="UT", value=end)
        except Exception as e:
            log(f"Error parsing dates for LT request: {e}")
            raise ValueError(
                "Error parsing dates for LT request, should be in ISO format"
            )

        return [airmass_const, sky_const, seeing_const, photom_const, date_const]

    def _build_target(self, request):
        """Payload target for all LT queue requests.

        Parameters
        ----------

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        Returns
        ----------
        target: etree.Element
            request xml target location.
        """

        target = etree.Element("Target", name=request.obj.id)
        c = SkyCoord(ra=request.obj.ra * u.degree, dec=request.obj.dec * u.degree)
        coordinates = etree.SubElement(target, "Coordinates")
        ra = etree.SubElement(coordinates, "RightAscension")
        etree.SubElement(ra, "Hours").text = str(int(c.ra.hms.h))
        etree.SubElement(ra, "Minutes").text = str(int(c.ra.hms.m))
        etree.SubElement(ra, "Seconds").text = str(c.ra.hms.s)

        dec = etree.SubElement(coordinates, "Declination")
        sign = "+" if c.dec.signed_dms.sign == 1.0 else "-"
        etree.SubElement(dec, "Degrees").text = sign + str(int(c.dec.signed_dms.d))
        etree.SubElement(dec, "Arcminutes").text = str(int(c.dec.signed_dms.m))
        etree.SubElement(dec, "Arcseconds").text = str(c.dec.signed_dms.s)
        etree.SubElement(coordinates, "Equinox").text = "J2000"
        return target


class IOOIOIRequest(LTRequest):
    """An XML structure for LT IOO/IOI requests."""

    def __init__(self, instname, request):
        """Initialize IOO/IOI request.

        Parameters
        ----------

        instname: str
            IO:O or IO:I.

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        """

        self.observation_payload = self._build_prolog(request)
        self._build_project(self.observation_payload, request)
        self._build_inst_schedule(instname, self.observation_payload, request)

    def _build_inst_schedule(self, instname, payload, request):
        """Payload header for LT IOO/IOI queue requests.

        Parameters
        ----------

        instname: str
            IO:O or IO:I.

        payload: etree.Element
            payload for requests.

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        Returns
        ----------
        payload: etree.Element
            payload for LT requests.
        """

        exp_time = request.payload["exposure_time"]
        exp_count = int(request.payload["exposure_counts"])
        for filt in request.payload["observation_choices"]:
            payload.append(
                self._build_schedule(instname, request, filt, exp_time, exp_count)
            )

    def _build_schedule(self, instname, request, filt, exp_time, exp_count):
        """Payload schedule for LT IOO queue requests.

        Parameters
        ----------

        instname: str
            IO:O or IO:I.

        payload: etree.Element
            payload for LT requests.

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        filt: str
            Exposure filter [u, g, r, i, z, H]

        exp_time: float
            Exposure time [s]

        exp_count: int
            Number of exposures

        Returns
        ----------
        schedule: etree.Element
            payload schedule for LT requests.
        """

        schedule = etree.Element("Schedule")
        device = etree.SubElement(schedule, "Device", name=instname, type="camera")
        if instname == "IO:O":
            etree.SubElement(device, "SpectralRegion").text = "optical"
        elif instname == "IO:I":
            etree.SubElement(device, "SpectralRegion").text = "infrared"

        setup = etree.SubElement(device, "Setup")
        etree.SubElement(setup, "Filter", type=filt.upper())
        detector = etree.SubElement(setup, "Detector")
        binning = etree.SubElement(detector, "Binning")
        etree.SubElement(binning, "X", units="pixels").text = "2"
        etree.SubElement(binning, "Y", units="pixels").text = "2"
        exposure = etree.SubElement(schedule, "Exposure", count=str(exp_count))
        etree.SubElement(exposure, "Value", units="seconds").text = str(exp_time)
        schedule.append(self._build_target(request))
        for const in self._build_constraints(request):
            schedule.append(const)
        return schedule


class SPRATRequest(LTRequest):
    """An XML structure for LT SPRAT requests."""

    def __init__(self, request):
        """Initialize SPRAT request.

        Parameters
        ----------

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        """

        self.observation_payload = self._build_prolog(request)
        self._build_project(self.observation_payload, request)
        self._build_inst_schedule(self.observation_payload, request)

    def _build_inst_schedule(self, payload, request):
        """Payload header for LT SPRAT queue requests.

        Parameters
        ----------

        payload: etree.Element
            payload for requests.

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        Returns
        ----------
        payload: etree.Element
            payload for requests.
        """

        self._build_SPRAT_schedule(payload, request)

    def _build_SPRAT_schedule(self, payload, request):
        """Payload schedule for LT SPRAT queue requests.

        Parameters
        ----------

        payload: etree.Element
            payload for requests.

        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.

        Returns
        ----------
        schedule:
            payload schedule for requests.
        """

        grating = request.payload["observation_type"]
        exp_time = request.payload["exposure_time"]
        exp_count = int(request.payload["exposure_counts"])

        schedule = etree.Element("Schedule")
        device = etree.SubElement(schedule, "Device", name="Sprat", type="spectrograph")
        etree.SubElement(device, "SpectralRegion").text = "optical"
        setup = etree.SubElement(device, "Setup")
        etree.SubElement(setup, "Grating", name=grating)
        detector = etree.SubElement(setup, "Detector")
        binning = etree.SubElement(detector, "Binning")
        etree.SubElement(binning, "X", units="pixels").text = "1"
        etree.SubElement(binning, "Y", units="pixels").text = "1"
        exposure = etree.SubElement(schedule, "Exposure", count=str(exp_count))
        etree.SubElement(exposure, "Value", units="seconds").text = str(exp_time)
        schedule.append(self._build_target(request))
        for const in self._build_constraints(request):
            schedule.append(const)
        payload.append(schedule)


class LTAPI(FollowUpAPI):
    """An interface to LT operations."""

    @staticmethod
    def delete(request, session, **kwargs):
        """Delete a follow-up request from LT queue (all instruments).

        Parameters
        ----------
        request: skyportal.models.FollowupRequest
            The request to delete from the queue and the SkyPortal database.
        session: sqlalchemy.Session
            Database session for this transaction
        """

        from ..models import FacilityTransaction

        altdata = request.allocation.altdata
        if not altdata:
            raise ValueError("Missing allocation information.")

        last_modified_by_id = request.last_modified_by_id
        obj_internal_key = request.obj.internal_key

        content = request.transactions[0].response["response"]
        response_rtml = etree.fromstring(content)
        uid = response_rtml.get("uid")

        headers = {
            "Username": altdata["username"],
            "Password": altdata["password"],
        }
        url = f"http://{cfg['app.lt_host']}:{cfg['app.lt_port']}/node_agent2/node_agent?wsdl"

        namespaces = {
            "xsi": LT_XSI_NS,
        }
        schemaLocation = etree.QName(LT_XSI_NS, "schemaLocation")
        cancel_payload = etree.Element(
            "RTML",
            {schemaLocation: LT_SCHEMA_LOCATION},
            mode="abort",
            uid=format(str(uid)),
            version="3.1a",
            nsmap=namespaces,
        )
        project = etree.SubElement(
            cancel_payload, "Project", ProjectID=altdata["LT_proposalID"]
        )
        contact = etree.SubElement(project, "Contact")
        etree.SubElement(contact, "Username").text = altdata["username"]
        etree.SubElement(contact, "Name").text = altdata["username"]
        etree.SubElement(contact, "Communication")
        cancel = etree.tostring(cancel_payload, encoding="unicode", pretty_print=True)

        client = Client(url=url, headers=headers)
        # Send cancel_payload, and receive response string, removing the encoding tag which causes issue with lxml parsing
        response = client.service.handle_rtml(cancel).replace(
            'encoding="ISO-8859-1"', ""
        )
        response_rtml = etree.fromstring(response)
        mode = response_rtml.get("mode")
        if mode in ["confirm", "reject"]:
            if mode == "confirm":
                request.status = "deleted"

            transaction = FacilityTransaction(
                request=http.serialize_requests_request_xml(cancel),
                response=http.serialize_requests_response_xml(response),
                followup_request=request,
                initiator_id=request.last_modified_by_id,
            )
            session.add(transaction)

            if kwargs.get("refresh_source", False):
                flow = Flow()
                flow.push(
                    "*",
                    "skyportal/REFRESH_SOURCE",
                    payload={"obj_key": obj_internal_key},
                )
            if kwargs.get("refresh_requests", False):
                flow = Flow()
                flow.push(
                    last_modified_by_id,
                    "skyportal/REFRESH_FOLLOWUP_REQUESTS",
                )
        else:
            log(
                f"Unknown mode {mode} response from LT. Unable to delete request {request.id} from LT queue: {response}"
            )

    form_json_schema_altdata = {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "title": "Username",
            },
            "password": {
                "type": "string",
                "title": "Password",
            },
            "LT_proposalID": {
                "type": "string",
                "title": "LT Proposal ID",
            },
        },
    }


class IOOAPI(LTAPI):
    """An interface to LT IOO operations."""

    @staticmethod
    def submit(request, session, **kwargs):
        """Submit a follow-up request to LT's IOO.

        Parameters
        ----------
        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.
        session: sqlalchemy.Session
            Database session for this transaction
        """

        from ..models import FacilityTransaction

        altdata = request.allocation.altdata
        if not altdata:
            raise ValueError("Missing allocation information.")
        ltreq = IOOIOIRequest("IO:O", request)
        observation_payload = ltreq.observation_payload

        headers = {
            "Username": altdata["username"],
            "Password": altdata["password"],
        }
        url = f"http://{cfg['app.lt_host']}:{cfg['app.lt_port']}/node_agent2/node_agent?wsdl"
        client = Client(url=url, headers=headers)
        full_payload = etree.tostring(
            observation_payload, encoding="unicode", pretty_print=True
        )
        # Send payload, and receive response string, removing the encoding tag which causes issue with lxml parsing
        response = client.service.handle_rtml(full_payload).replace(
            'encoding="ISO-8859-1"', ""
        )
        response_rtml = etree.fromstring(response)
        mode = response_rtml.get("mode")

        if mode == "confirm":
            request.status = "submitted"
        else:
            error = list(response_rtml.iter("{http://www.rtml.org/v3.1a}Error"))[0].text
            request.status = f"rejected: {error}"
            log(
                f"Failed to submit IOO request: {str(error)}. Full payload: {str(full_payload)}"
            )
            try:
                flow = Flow()
                flow.push(
                    request.last_modified_by_id,
                    "baselayer/SHOW_NOTIFICATION",
                    payload={
                        "note": f"Failed to submit IOO request: {error}",
                        "type": "error",
                    },
                )
            except Exception as e:
                log(f"Failed to send notification: {e}")

        transaction = FacilityTransaction(
            request=http.serialize_requests_request_xml(full_payload),
            response=http.serialize_requests_response_xml(response),
            followup_request=request,
            initiator_id=request.last_modified_by_id,
        )

        session.add(transaction)

        if kwargs.get("refresh_source", False):
            flow = Flow()
            flow.push(
                "*",
                "skyportal/REFRESH_SOURCE",
                payload={"obj_key": request.obj.internal_key},
            )
        if kwargs.get("refresh_requests", False):
            flow = Flow()
            flow.push(
                request.last_modified_by_id,
                "skyportal/REFRESH_FOLLOWUP_REQUESTS",
            )

    form_json_schema = {
        "type": "object",
        "properties": {
            "observation_choices": {
                "type": "array",
                "title": "Desired Observations",
                "items": {"type": "string", "enum": ["u", "g", "r", "i", "z"]},
                "uniqueItems": True,
                "minItems": 1,
            },
            "exposure_time": {
                "title": "Exposure Time [s]",
                "type": "number",
                "default": 300.0,
            },
            "exposure_counts": {
                "title": "Exposure Counts",
                "type": "number",
                "default": 1,
            },
            "start_date": {
                "type": "string",
                "default": datetime.utcnow().isoformat(),
                "title": "Start Date (UT)",
            },
            "end_date": {
                "type": "string",
                "title": "End Date (UT)",
                "default": (datetime.utcnow() + timedelta(days=7)).isoformat(),
            },
            "maximum_airmass": {
                "title": "Maximum Airmass (1-3)",
                "type": "number",
                "default": 2.0,
                "minimum": 1,
                "maximum": 3,
            },
            "maximum_seeing": {
                "title": "Maximum Seeing [arcsec] (0-5)",
                "type": "number",
                "default": 1.2,
                "minimum": 0,
                "maximum": 5,
            },
            "sky_brightness": {
                "title": "Maximum allowable Sky Brightness, Dark + X magnitudes [arcsec] (0-5)",
                "type": "number",
                "default": 2.0,
                "minimum": 0,
                "maximum": 5,
            },
            "photometric": {
                "title": "Does this observation require photometric conditions?",
                "type": "boolean",
            },
        },
        "required": [
            "observation_choices",
            "exposure_time",
            "exposure_counts",
            "start_date",
            "end_date",
            "maximum_airmass",
            "maximum_seeing",
        ],
    }

    ui_json_schema = {"observation_choices": {"ui:widget": "checkboxes"}}


class IOIAPI(LTAPI):
    """An interface to LT IOI operations."""

    @staticmethod
    def submit(request, session, **kwargs):
        """Submit a follow-up request to LT's IOI.

        Parameters
        ----------
        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.
        session: sqlalchemy.Session
            Database session for this transaction
        """

        from ..models import FacilityTransaction

        altdata = request.allocation.altdata
        if not altdata:
            raise ValueError("Missing allocation information.")
        ltreq = IOOIOIRequest("IO:I", request)
        observation_payload = ltreq.observation_payload

        headers = {
            "Username": altdata["username"],
            "Password": altdata["password"],
        }
        url = f"http://{cfg['app.lt_host']}:{cfg['app.lt_port']}/node_agent2/node_agent?wsdl"
        client = Client(url=url, headers=headers)
        full_payload = etree.tostring(
            observation_payload, encoding="unicode", pretty_print=True
        )
        # Send payload, and receive response string, removing the encoding tag which causes issue with lxml parsing
        response = client.service.handle_rtml(full_payload).replace(
            'encoding="ISO-8859-1"', ""
        )
        response_rtml = etree.fromstring(response)
        mode = response_rtml.get("mode")

        if mode == "confirm":
            request.status = "submitted"
        else:
            error = list(response_rtml.iter("{http://www.rtml.org/v3.1a}Error"))[0].text
            request.status = f"rejected: {error}"
            log(
                f"Failed to submit IOI request: {str(error)}. Full payload: {str(full_payload)}"
            )
            try:
                flow = Flow()
                flow.push(
                    request.last_modified_by_id,
                    "baselayer/SHOW_NOTIFICATION",
                    payload={
                        "note": f"Failed to submit IOI request: {error}",
                        "type": "error",
                    },
                )
            except Exception as e:
                log(f"Failed to send notification: {e}")

        transaction = FacilityTransaction(
            request=http.serialize_requests_request_xml(full_payload),
            response=http.serialize_requests_response_xml(response),
            followup_request=request,
            initiator_id=request.last_modified_by_id,
        )

        session.add(transaction)

        if kwargs.get("refresh_source", False):
            flow = Flow()
            flow.push(
                "*",
                "skyportal/REFRESH_SOURCE",
                payload={"obj_key": request.obj.internal_key},
            )
        if kwargs.get("refresh_requests", False):
            flow = Flow()
            flow.push(
                request.last_modified_by_id,
                "skyportal/REFRESH_FOLLOWUP_REQUESTS",
            )

    form_json_schema = {
        "type": "object",
        "properties": {
            "observation_choices": {
                "type": "array",
                "title": "Desired Observations",
                "items": {"type": "string", "enum": ["H"]},
                "uniqueItems": True,
                "minItems": 1,
            },
            "exposure_time": {
                "title": "Exposure Time [s]",
                "type": "number",
                "default": 300.0,
            },
            "exposure_counts": {
                "title": "Exposure Counts",
                "type": "number",
                "default": 1,
            },
            "start_date": {
                "type": "string",
                "default": datetime.utcnow().isoformat(),
                "title": "Start Date (UT)",
            },
            "end_date": {
                "type": "string",
                "title": "End Date (UT)",
                "default": (datetime.utcnow() + timedelta(days=7)).isoformat(),
            },
            "maximum_airmass": {
                "title": "Maximum Airmass (1-3)",
                "type": "number",
                "default": 2.0,
                "minimum": 1,
                "maximum": 3,
            },
            "maximum_seeing": {
                "title": "Maximum Seeing [arcsec] (0-5)",
                "type": "number",
                "default": 1.2,
                "minimum": 0,
                "maximum": 5,
            },
            "sky_brightness": {
                "title": "Maximum allowable Sky Brightness, Dark + X magnitudes [arcsec] (0-5)",
                "type": "number",
                "default": 2.0,
                "minimum": 0,
                "maximum": 5,
            },
            "photometric": {
                "title": "Does this observation require photometric conditions?",
                "type": "boolean",
            },
        },
        "required": [
            "observation_choices",
            "exposure_time",
            "exposure_counts",
            "start_date",
            "end_date",
            "maximum_airmass",
            "maximum_seeing",
        ],
    }

    ui_json_schema = {"observation_choices": {"ui:widget": "checkboxes"}}


class SPRATAPI(LTAPI):
    """An interface to LT SPRAT operations."""

    @staticmethod
    def submit(request, session, **kwargs):
        """Submit a follow-up request to LT's SPRAT.

        Parameters
        ----------
        request: skyportal.models.FollowupRequest
            The request to add to the queue and the SkyPortal database.
        session: sqlalchemy.Session
            Database session for this transaction
        """

        from ..models import FacilityTransaction

        altdata = request.allocation.altdata
        if not altdata:
            raise ValueError("Missing allocation information.")

        ltreq = SPRATRequest(request)
        observation_payload = ltreq.observation_payload

        headers = {
            "Username": altdata["username"],
            "Password": altdata["password"],
        }
        url = f"http://{cfg['app.lt_host']}:{cfg['app.lt_port']}/node_agent2/node_agent?wsdl"
        client = Client(url=url, headers=headers)
        full_payload = etree.tostring(
            observation_payload, encoding="unicode", pretty_print=True
        )
        # Send payload, and receive response string, removing the encoding tag which causes issue with lxml parsing
        response = client.service.handle_rtml(full_payload).replace(
            'encoding="ISO-8859-1"', ""
        )
        response_rtml = etree.fromstring(response)
        mode = response_rtml.get("mode")

        if mode == "confirm":
            request.status = "submitted"
        else:
            error = list(response_rtml.iter("{http://www.rtml.org/v3.1a}Error"))[0].text
            request.status = f"rejected: {error}"
            log(
                f"Failed to submit SPRAT request: {str(error)}. Full payload: {str(full_payload)}"
            )
            try:
                flow = Flow()
                flow.push(
                    request.last_modified_by_id,
                    "baselayer/SHOW_NOTIFICATION",
                    payload={
                        "note": f"Failed to submit SPRAT request: {error}",
                        "type": "error",
                    },
                )
            except Exception as e:
                log(f"Failed to send notification: {e}")

        transaction = FacilityTransaction(
            request=http.serialize_requests_request_xml(full_payload),
            response=http.serialize_requests_response_xml(response),
            followup_request=request,
            initiator_id=request.last_modified_by_id,
        )

        session.add(transaction)

        if kwargs.get("refresh_source", False):
            flow = Flow()
            flow.push(
                "*",
                "skyportal/REFRESH_SOURCE",
                payload={"obj_key": request.obj.internal_key},
            )
        if kwargs.get("refresh_requests", False):
            flow = Flow()
            flow.push(
                request.last_modified_by_id,
                "skyportal/REFRESH_FOLLOWUP_REQUESTS",
            )

    form_json_schema = {
        "type": "object",
        "properties": {
            "observation_type": {
                "type": "string",
                "enum": ["blue", "red"],
                "default": "blue",
            },
            "exposure_time": {
                "title": "Exposure Time [s]",
                "type": "number",
                "default": 300.0,
            },
            "exposure_counts": {
                "title": "Exposure Counts",
                "type": "number",
                "default": 1,
            },
            "start_date": {
                "type": "string",
                "default": datetime.utcnow().isoformat(),
                "title": "Start Date (UT)",
            },
            "end_date": {
                "type": "string",
                "title": "End Date (UT)",
                "default": (datetime.utcnow() + timedelta(days=7)).isoformat(),
            },
            "maximum_airmass": {
                "title": "Maximum Airmass (1-3)",
                "type": "number",
                "default": 2.0,
                "minimum": 1,
                "maximum": 3,
            },
            "maximum_seeing": {
                "title": "Maximum Seeing [arcsec] (0-5)",
                "type": "number",
                "default": 1.2,
                "minimum": 0,
                "maximum": 5,
            },
            "sky_brightness": {
                "title": "Maximum allowable Sky Brightness, Dark + X magnitudes [arcsec] (0-5)",
                "type": "number",
                "default": 2.0,
                "minimum": 0,
                "maximum": 5,
            },
            "photometric": {
                "title": "Does this observation require photometric conditions?",
                "type": "boolean",
            },
        },
        "required": [
            "observation_type",
            "start_date",
            "end_date",
            "maximum_airmass",
            "maximum_seeing",
        ],
    }

    ui_json_schema = {}
