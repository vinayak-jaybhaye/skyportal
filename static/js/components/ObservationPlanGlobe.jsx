import React, { useState, useEffect } from "react";
import PropTypes from "prop-types";
import { useDispatch } from "react-redux";

import CircularProgress from "@mui/material/CircularProgress";

import GeoPropTypes from "geojson-prop-types";

import * as Actions from "../ducks/gcnEvent";
import { GET } from "../API";
import Button from "./Button";

import LocalizationPlot from "./LocalizationPlot";

const ObservationPlanGlobe = ({
  observationplanRequest,
  retrieveLocalization,
}) => {
  const dispatch = useDispatch();

  const displayOptions = [
    "localization",
    "sources",
    "galaxies",
    "instrument",
    "observations",
  ];
  const displayOptionsDefault = Object.fromEntries(
    displayOptions.map((x) => [x, false]),
  );
  displayOptionsDefault.localization = true;
  displayOptionsDefault.observations = true;

  const [obsList, setObsList] = useState(null);
  const [localization, setLocalization] = useState(null);

  useEffect(() => {
    const fetchObsList = async () => {
      const response = await dispatch(
        GET(
          `/api/observation_plan/${observationplanRequest.id}/geojson`,
          "skyportal/FETCH_OBSERVATION_PLAN_GEOJSON",
        ),
      );
      setObsList(response.data);
    };
    if (
      ["complete", "submitted to telescope queue"].includes(
        observationplanRequest?.status,
      )
    ) {
      fetchObsList();
    }
  }, [dispatch, setObsList, observationplanRequest]);

  useEffect(() => {
    const fetchLocalization = async () => {
      const response = await dispatch(
        GET(
          `/api/localization/${observationplanRequest.localization.dateobs}/name/${observationplanRequest.localization.localization_name}`,
          "skyportal/FETCH_LOCALIZATION_OBSPLAN",
        ),
      );
      setLocalization(response.data);
    };
    if (retrieveLocalization) {
      fetchLocalization();
    }
  }, [dispatch, setLocalization, observationplanRequest]);

  const handleDeleteObservationPlanFields = async (obsPlanList) => {
    const selectedFields = obsPlanList?.geojson.filter((f) => f?.selected);
    const selectedIds = selectedFields.map((f) => f?.properties?.field_id);
    await dispatch(
      Actions.deleteObservationPlanFields(
        observationplanRequest.id,
        selectedIds,
      ),
    );
  };

  return (
    <div>
      {!obsList ? (
        <div>
          <CircularProgress />
        </div>
      ) : (
        <div>
          <LocalizationPlot
            localization={localization}
            observations={obsList}
            options={displayOptionsDefault}
            height={550}
            width={550}
            type="obsplan"
            projection="mollweide"
          />
          <Button
            secondary
            onClick={() => handleDeleteObservationPlanFields(obsList)}
          >
            Delete selected fields
          </Button>
        </div>
      )}
    </div>
  );
};

ObservationPlanGlobe.propTypes = {
  observationplanRequest: PropTypes.shape({
    id: PropTypes.number,
    requester: PropTypes.shape({
      id: PropTypes.number,
      username: PropTypes.string,
    }),
    instrument: PropTypes.shape({
      id: PropTypes.number,
      name: PropTypes.string,
    }),
    status: PropTypes.string,
    allocation: PropTypes.shape({
      group: PropTypes.shape({
        name: PropTypes.string,
      }),
    }),
    localization: PropTypes.shape({
      id: PropTypes.number,
      dateobs: PropTypes.string,
      localization_name: PropTypes.string,
      contour: GeoPropTypes.FeatureCollection,
    }),
  }).isRequired,
  retrieveLocalization: PropTypes.bool,
};

ObservationPlanGlobe.defaultProps = {
  retrieveLocalization: false,
};

export default ObservationPlanGlobe;
