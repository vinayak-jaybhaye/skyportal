import copy
import os

import yaml
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone

from baselayer.app.access import auth_or_token
from baselayer.app.env import load_env
from baselayer.log import make_log

from ...models import (
    User,
)
from ..base import BaseHandler

_, cfg = load_env()
log = make_log("query")


# add in this new search method to the Pinecone class
def search_sources(
    client: Pinecone,
    query: str,
    k: int = 4,
    filter: dict | None = None,
    index_name: str | None = None,
    namespace: str | None = None,
    openai_api_key: str | None = None,
) -> list[dict]:
    """Return pinecone documents most similar to query, along with scores.

    Args:
        client: Pinecone client object.
        query: Text to look up documents similar to.
        k: Number of Documents to return. Defaults to 4.
        filter: Dictionary of argument(s) to filter on metadata
        index_name: Name of the index to search in.
        namespace: Namespace to search in. Default will search in '' namespace.
        openai_api_key: OpenAI API key to use for embeddings.
    Returns:
        List of source dictionaries most similar to the query and score for each
    """
    if client is None:
        raise ValueError("pinecone_client must be provided")
    if index_name is None:
        raise ValueError("index_name must be provided")
    if openai_api_key is None:
        raise ValueError("openai_api_key must be provided")

    embeddings = OpenAIEmbeddings(
        model=summarize_embedding_model,
        embedding_ctx_length=summarize_embedding_index_size,
        openai_api_key=openai_api_key,
    )
    query_vector = embeddings.embed_query(query)

    index = client.Index(index_name)
    results = index.query(
        top_k=k,
        vector=query_vector,
        include_values=False,
        include_metadata=True,
        namespace=namespace,
        filter=filter,
    )

    sources = []
    for res in results["matches"]:
        try:
            source = {
                "id": res["id"],
                "score": res["score"],
                "metadata": res["metadata"],
            }
            sources.append(source)
        except Exception as e:
            log(f"Error: {e}")
            continue
    return sources


pinecone_client = None

# Preamble: get the embeddings and summary parameters ready
# for now, we only support pinecone embeddings
summarize_embedding_config = cfg[
    "analysis_services.openai_analysis_service.embeddings_store.summary"
]
USE_PINECONE = False
if (
    summarize_embedding_config.get("location") == "pinecone"
    and summarize_embedding_config.get("api_key")
    and summarize_embedding_config.get("index_name")
    and summarize_embedding_config.get("index_size")
):
    log("initializing pinecone access...")
    pinecone_client = Pinecone(
        api_key=summarize_embedding_config.get("api_key"),
    )

    summarize_embedding_index_name = summarize_embedding_config.get("index_name")
    summarize_embedding_index_size = summarize_embedding_config.get("index_size")
    summarize_embedding_model = summarize_embedding_config.get("model")

    if summarize_embedding_index_name in [
        index.name for index in pinecone_client.list_indexes().indexes
    ]:
        USE_PINECONE = True
else:
    if cfg["database.database"] == "skyportal_test":
        USE_PINECONE = True
        log("Setting USE_PINECONE=True as it seems like we are in a test environment")
    else:
        log("No valid pinecone configuration found. Please check the config file.")

summary_config = copy.deepcopy(cfg["analysis_services.openai_analysis_service.summary"])
if summary_config.get("api_key"):
    # there may be a global API key set in the config file
    openai_api_key = summary_config.pop("api_key")
elif os.path.exists(".secret"):
    # try to get this key from the dev environment, useful for debugging
    openai_api_key = yaml.safe_load(open(".secret")).get("OPENAI_API_KEY")
elif cfg["database.database"] == "skyportal_test":
    openai_api_key = "TEST_KEY"
else:
    openai_api_key = None


class SummaryQueryHandler(BaseHandler):
    @auth_or_token
    def post(self):
        """
        ---
        summary: Search for sources based on their summaries
        description: Get a list of sources with summaries matching the query
        tags:
          - summary
        parameters:
        - in: query
          name: q
          schema:
              type: string
          description: |
              The query string. E.g. "What sources are associated with
              an NGC galaxy?"
        - in: query
          name: objID
          schema:
              type: string
          description: |
              The objID of the source which has a summary to be used as the query.
              That is, return the list of sources most similar to the summary of
                this source. Ignored if q is provided.
        - in: query
          name: k
          schema:
              type: int
          minimum: 1
          maximum: 100
          description: |
              Max number of sources to return. Default 5.
        - in: query
          name: z_min
          schema:
              type: float
          nullable: true
          description: |
              Minimum redshift to consider of queries sources. If None or missing,
              then no lower limit is applied.
        - in: query
          name: z_max
          schema:
              type: float
          nullable: true
          description: |
              Maximum redshift to consider of queries sources. If None or missing,
              then no upper limit is applied.
        - in: query
          name: classificationTypes
          nullable: true
          schema:
              type: array
              items:
                  type: string
          description: |
              List of classification types to consider. If [] or missing,
              then all classification types are considered.
        responses:
          200:
            content:
              application/json:
                schema:
                  allOf:
                    - $ref: '#/components/schemas/Success'
                    - type: object
                      properties:
                        data:
                          type: object
                          properties:
                            sources:
                              type: array
                              items:
                                $ref: '#/components/schemas/Obj'
          400:
            content:
              application/json:
                schema: Error
        """

        if not USE_PINECONE:
            return self.error(
                "No valid pinecone configuration found. Please check your config file."
            )
        user_openai_key = None
        if not openai_api_key:
            user_id = self.associated_user_object.id
            with self.Session() as session:
                user = session.scalars(
                    User.select(session.user_or_token, mode="read").where(
                        User.id == user_id
                    )
                ).first()
                if user is None:
                    return self.error(
                        "No global OpenAI key found and cannot find user.", status=400
                    )

                if user.preferences is not None and user.preferences.get(
                    "summary", {}
                ).get("OpenAI", {}).get("active", False):
                    user_pref_openai = user.preferences["summary"]["OpenAI"].get(
                        "apikey"
                    )
                    user_openai_key = user_pref_openai["apikey"]
        else:
            user_openai_key = openai_api_key
        if not user_openai_key:
            return self.error("No OpenAI API key found.", status=400)

        data = self.get_json()
        query = data.get("q")
        objID = data.get("objID")
        if query in [None, ""] and objID in [None, ""]:
            return self.error('Missing one of the required: "q" or "objID"')
        if query is not None and objID is not None:
            return self.error('Cannot specify both "q" and "objID"')

        search_by_string = query not in [None, ""]
        k = data.get("k", 5)
        if k < 1 or k > 100:
            return self.error("k must be 1<=k<=100")
        z_min = data.get("z_min", None)
        z_max = data.get("z_max", None)
        if z_min is not None and z_max is not None and z_min > z_max:
            return self.error("z_min must be <= z_max")
        classification_types = data.get("classificationTypes", None)

        # construct the filter
        if z_min is not None and z_max is None:
            z_filt = {"redshift": {"$gte": z_min}}
        elif z_min is None and z_max is not None:
            z_filt = {"redshift": {"$lte": z_max}}
        elif z_min is not None and z_max is not None:
            z_filt = {
                "$and": [{"redshift": {"$gte": z_min}}, {"redshift": {"$lte": z_max}}]
            }
        else:
            z_filt = None
        if classification_types not in [None, []]:
            class_filt = {"class": {"$in": classification_types}}
        else:
            class_filt = None

        if class_filt is not None and z_filt is not None:
            filt = {"$and": [class_filt, z_filt]}
        elif class_filt is not None:
            filt = class_filt
        elif z_filt is not None:
            filt = z_filt
        else:
            filt = {}

        if search_by_string:
            # get the top k sources
            try:
                results = search_sources(
                    pinecone_client,
                    query,
                    k,
                    filt,
                    summarize_embedding_index_name,
                    "",
                    user_openai_key,
                )
            except Exception as e:
                return self.error(f"Could not search sources: {e}")
        else:
            # search by objID. Will return an empty list if objID not in
            # vector database.
            try:
                index = pinecone_client.Index(summarize_embedding_index_name)
                query_response = index.query(
                    top_k=k,
                    index=summarize_embedding_index_name,
                    include_values=False,
                    include_metadata=True,
                    id=objID,
                    filter=filt,
                )
                results = query_response.get("matches", [])
            except Exception as e:
                return self.error(f"Could not query index: {e}")

        return self.success(data={"query_results": results})
