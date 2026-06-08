from openai import OpenAI
from databricks.sdk import WorkspaceClient
 
# DATABRICKS_HOST = "https://dbc-8cdf719f-e0fb.cloud.databricks.com"
# DATABRICKS_HOST = "https://dbc-33376193-7527.cloud.databricks.com"

w = WorkspaceClient(profile="WORKSPACE_EUROPE_DEV")

 
# w = WorkspaceClient(host=DATABRICKS_HOST)
token = w.config.authenticate()["Authorization"].removeprefix("Bearer ")

me = w.current_user.me()
print(f"User name: {me.user_name}")
print(f"Token: {token}")
print(f"DATABRICKS_HOST: {w.config.host}")

for catalog in w.catalogs.list():
    print(f"Catalog: {catalog.name}")

for wh in w.warehouses.list():
    print(f"Warehouse: {wh.name}")
    print(f"ID: {wh.id}")
    print(f"State: {wh.state}")
    # print(f"Default catalog: {wh.default_catalog}")
    # print(f"Default schema: {wh.default_schema}")
    print(f"Tags: {wh.tags}")
    # print(f"Created at: {wh.created_at}")
    # print(f"Updated at: {wh.updated_at}")
    # print(f"Created by: {wh.created_by}")
    # print(f"Updated by: {wh.updated_by}")
    # print(f"Created by: {wh.created_by}")

exit()
client = OpenAI(
  api_key=token,
  base_url=f"{w.config.host}/ai-gateway/mlflow/v1"
)
 
chat_completion = client.chat.completions.create(
  messages=[
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hello! How can I assist you today?"},
    {"role": "user", "content": "What is Databricks?"},
  ],
  model="databricks-claude-opus-4-8",
  max_tokens=1024
)
 
print(chat_completion.choices[0].message.content)
    