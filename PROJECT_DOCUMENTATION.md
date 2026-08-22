# AnalyticsGPT-Copilot Technical & Architectural Documentation

This document explains the architecture, theoretical design, detailed module workflows, and exact function usages of the **AnalyticsGPT-Copilot** backend service.

---

## 1. Architectural Concepts & Theoretical Design

### AI Copilot & Dynamic Execution Paradigm
Traditionally, AI agents are built using static tool-calling frameworks (e.g., executing a pre-written function when a specific keyword is detected). While safe, this approach is extremely rigid. 

**AnalyticsGPT-Copilot** transitions from static routing to a **dynamic LLM-driven Pandas execution engine**. 
- **The Theory**: Instead of matching user inputs to predefined functions (like `dropna` or `groupby`), the LLM acts as a code-generation engine that synthesizes raw Python/Pandas scripts to fit arbitrary user queries.
- **The Execution**: The generated script is compiled and run inside a restricted local dictionary scope using Python's native `exec()` function. This enables the agent to solve complex multi-step data cleaning, advanced statistical operations, and bespoke plotting without the developer having to foresee and write handlers for every single command.
- **Error Handling (Self-Correction)**: Because code generation can fail (due to incorrect column names, syntax bugs, or shape mismatches), the agent uses a LangGraph conditional edge. When `exec()` throws an exception, the system catches the Python traceback, appends it to the query context, and prompts the LLM to self-correct the script.

### Memory & Context Persistence (MCP)
To maintain long-term memory across isolated WebSocket requests, the system implements a hybrid memory retrieval architecture combining **relational sliding-window context** with **semantic vector searches**.
- **Sliding-Window Memory (PostgreSQL)**: Captures the most recent $N$ messages of the session to maintain direct conversational continuity.
- **Semantic Memory (Qdrant)**: Embeds the user's current query into a 384-dimensional space using BGE-small. It runs a Cosine Similarity search against the historical messages database in Qdrant to pull relevant conversations from past sessions.
- **Deduplication & Union**: The context-merging service aggregates both lists, deduplicates matching items based on text hashing, and prepends semantic logs as background context for the LLM.

---

## 2. Detailed Project Workflows

### Upload & Storage Workflow
The file ingestion workflow is designed to avoid holding persistent state on the application server's local disk, enabling the service to scale across containerized instances (like Docker or Kubernetes) without state sync issues.
1. The client sends a file upload request (`UploadFile` multipart payload) to `/dataset/upload`.
2. The server reads the file stream into memory as raw bytes, validating file extension limits (.csv, .xlsx, .xls) and size restrictions (< 50MB).
3. The server generates a unique UUID (`dataset_id`) and writes the raw binary content directly to the `datasets` table in PostgreSQL.
4. The server returns the UUID as `file_path` to the client. This ID serves as a persistent database pointer.

### WebSocket Query & Analysis Workflow
1. The client initiates a WebSocket connection at `/chat/ws/{session_id}` and transmits a payload containing the query message, dataset ID (`file_path`), and model preference.
2. The API retrieves the session details from the in-memory cache and starts a background heartbeat ping loop.
3. If a dataset ID is present, the server instantiates a LangGraph state graph.
4. **Graph Step 1 (Router)**: The LLM classifies the query into one of three modes: `analytics`, `visualization`, or `etl`.
5. **Graph Step 2 (Dataset Loader)**: The database is queried for the binary dataset. The raw bytes are parsed into a Pandas DataFrame in-memory using `io.BytesIO` based on the file extension.
6. **Graph Step 3 (Planner)**: The LLM writes a Python snippet matching the requested mode and dataset schema, outputting a JSON object containing the code.
7. **Graph Step 4 (Executor)**: The executor compiles the code, executes it inside `exec()`, and retrieves the updated DataFrame or Plotly figure object. If a runtime crash occurs, the graph loops back to the planner to fix the script.
8. **Graph Step 5 (Explainer)**: The LLM describes the performed operations and insights.
9. **Graph Step 6 (Response)**: The formatted output (table JSON or Plotly figure JSON) is sent back to the client over the WebSocket.

---

## 3. Directory Structure & Detailed File Breaks

### Core Configuration & Security

#### `app/core/config.py`
Provides global environment configurations parsed via Pydantic.
- **`class Settings(BaseSettings)`**:
  - **Purpose**: Maps `.env` properties to strongly-typed Python attributes.
  - **Usage**: Serves configuration values for database connections, JWT signing, Qdrant host settings, and Groq API keys.
- **`get_settings() -> Settings`**:
  - **Purpose**: Instantiates and caches the settings object using `lru_cache` to prevent parsing the `.env` file repeatedly.

#### `app/core/security.py`
Handles cryptographic tasks and authentication checks.
- **`hash_password(password: str) -> str`**:
  - **Purpose**: Hashes user passwords before database storage.
  - **Mechanism**: Hashes the input with SHA-256 and context-salts it with Bcrypt.
- **`verify_password(plain: str, hashed: str) -> bool`**:
  - **Purpose**: Compares a plain text password attempt against the stored hash.
- **`create_access_token(data: dict, expires_delta: Optional[timedelta]) -> str`**:
  - **Purpose**: Generates a JWT access token for API authentication.
- **`create_refresh_token(data: dict) -> str`**:
  - **Purpose**: Generates a long-lived JWT refresh token.
- **`decode_token(token: str) -> dict`**:
  - **Purpose**: Decodes and validates JWT signatures.
- **`get_current_user_id(token: str) -> int`**:
  - **Purpose**: Dependency to authenticate Bearer tokens and return the User ID.
- **`verify_api_key(x_api_key: str)`**:
  - **Purpose**: Header validator verifying internal service keys.

#### `app/core/logging.py`
- **`setup_logging(level: str)`**: Initializes the global logger format and standard output stream.
- **`get_logger(name: str) -> Logger`**: Returns a module-specific logger instance.

---

### Database Connectivity & Models

#### `app/db/session.py`
- **`AsyncSessionLocal`**: Async sessionmaker utilizing `asyncpg` for standard database queries.
- **`sync_engine`**: Sync database engine utilizing `psycopg2` for migration scripts.
- **`get_db()`**: Async generator yielding active PostgreSQL session connections.

#### `app/models.py`
Declares SQLAlchemy declarative database mapping models.
- **`class User(Base)`**: Represents registered user profiles (username, email, pass hashes).
- **`class RefreshToken(Base)`**: Tracks issued refresh tokens for revocation and rotation checks.
- **`class ChatSession(Base)`**: Records completed chat sessions.
- **`class Message(Base)`**: Persists standard message entities.
- **`class Dataset(Base)`**:
  - **Purpose**: Holds uploaded datasets.
  - **Fields**: `dataset_id` (UUID primary key), `filename` (source filename), `content` (raw binary bytes stored as `LargeBinary`).

---

### API Routers

#### `app/api/auth.py`
- **`register(user_schema, db) -> token`**: Creates user profiles, raising errors if conflicts occur.
- **`login(credentials, db) -> tokens`**: Verifies password hashes and issues access and refresh tokens.
- **`refresh(token, db) -> tokens`**: Generates new short-term access tokens using a valid refresh token.

#### `app/api/dataset.py`
- **`upload_dataset(file, user_id, db) -> dict`**:
  - **Purpose**: Receives dataset uploads.
  - **Mechanism**: Reads files into memory, validates constraints, instantiates a `Dataset` model, commits it to the database, and returns the UUID as `file_path`.

#### `app/api/chat.py`
Orchestrates WebSocket connections and fallback pathways.
- **`class ConnectionManager`**:
  - `connect(ws, session_id)`: Accepts the socket and registers it to the session.
  - `disconnect(session_id)`: Removes connections from the active pool.
  - `send_json(session_id, data)`: Transmits JSON payloads over the socket.
  - `send_error(session_id, error)`: Transmits formatted error strings.
- **`delete_session(session_id, user_id, db)`**:
  - **Purpose**: DELETE endpoint removing chat histories.
  - **Mechanism**: Invokes `mcp_service.delete_session` to drop both relational PostgreSQL database logs and semantic Qdrant vectors.
- **`websocket_chat(websocket, session_id, db)`**:
  - **Purpose**: Main WebSocket connection loop.
  - **Mechanism**: Handles heartbeats, receives user messages, and parses client-requested model arguments. If `file_path` (dataset ID) is present, it runs the LangGraph engine; otherwise, it queries the Groq API using `mcp_service.build_context` for a standard conversational response. Automatically triggers `mcp_service.save_session` incrementally on every message turn to prevent chat loss and update the sidebar immediately.

#### `app/api/health.py`
- **`readiness(db)`**: Performs active connection checks on PostgreSQL, Qdrant, and the Groq configuration status.

---

### LangGraph Agent Framework

#### `app/agents/state.py`
- **`class AgentState(TypedDict)`**:
  - **Purpose**: Represents the shared state dictionary passed between nodes in the LangGraph execution flow.
  - **Keys**: `user_id`, `message` (query), `mode`, `file_path` (dataset UUID), `model` (selected model), `df` (parsed DataFrame), `schema` (column string), `plan` (JSON containing code), `result` (executed result data), `logs` (step logs), `error`, `fatal_error`, `retry_count`, `explanation`, `final`.

#### `app/agents/graph.py`
- **`should_retry(state) -> str`**:
  - **Purpose**: Conditional routing checker.
  - **Logic**: If an error is present, `fatal_error` is false, and retry count is less than 3, it returns `"retry"` to route to the retry node; otherwise, it returns `"continue"`.
- **`build_graph() -> CompiledGraph`**: Combines nodes and sets edges.

#### `app/agents/nodes.py`
Houses the execution nodes for the LangGraph pipeline.
- **`router_node(state)`**: Categorizes queries into mode types using `router_service.route`.
- **`dataset_node(state)`**:
  - **Purpose**: Fetches the binary dataset content from the database.
  - **Mechanism**: Uses `AsyncSessionLocal` to fetch the binary blob by UUID, reads the file name extension, and loads the data into `pd.read_csv` or `pd.read_excel` via `io.BytesIO`.
- **`planner_node(state)`**: Formulates a Pandas/Plotly python script using `planner_service.create_plan`.
- **`executor_node(state)`**: Runs the generated python script using `executor_service.execute`.
- **`retry_node(state)`**: Prompts the LLM with the failed Python code and traceback error to obtain a corrected script.
- **`explanation_node(state)`**: Explains the executed script using `explanation_service.generate`.
- **`response_node(state)`**: Formats the state results into final text for WebSocket dispatch.

---

### Services

#### `app/services/llm_service.py`
- **`ALLOWED_MODELS = {"openai/gpt-oss-120b", "qwen/qwen3.6-27b"}`**
- **`class LLMService`**:
  - **Purpose**: Core interface for Groq API text generation.
  - **`generate(messages, model)`**:
    - **Mechanism**: Ensures the model is allowed. Prepends `SYSTEM_PROMPT` to the message array. Sends an async POST request to the Groq completion endpoint. Returns the generated response string and the exact token usage count.
  - **`generate_sync(messages, model)`**: Synchronous HTTP version used for warming and checks at startup.

#### `app/services/embedding_service.py`
- **`class EmbeddingService`**:
  - **Purpose**: Generates vector representations for semantic search.
  - **Mechanism**: Checks if the background `embedding_daemon` is running on port 8001; if not, automatically spawns it. Queries the daemon to get embeddings instantly (preventing slow loading times on code hot-reloads). If the daemon fails to respond, dynamically falls back to loading the model in-process.

#### `app/services/embedding_daemon.py`
- **Purpose**: Standalone microservice running the SentenceTransformer model on port 8001.
- **Port Allocation Rationale**: Runs on port 8001 to avoid TCP port conflicts with the main FastAPI server (which binds to port 8000). The main application communicates with the daemon via local loopback HTTP POST requests.
- **Caching & Unload Logic**: Persists the loaded model in memory across main app process reloads. Implements a 1-hour idle timeout garbage-collection check; if no queries are received for 1 hour, it unloads the model from RAM to free system memory, and reloads it on demand.

#### `app/services/qdrant_service.py`
- **`class QdrantService`**:
  - **Purpose**: Interfaces with the Qdrant vector database.
  - **`search(query_vector, user_id, limit, score_threshold)`**: Queries the collection, filtering by `user_id` and matching embeddings above the similarity score threshold.

#### `app/services/mcp_service.py`
- **`class MCPService`**:
  - **`save_session(db, session_data)`**: Saves messages to PostgreSQL and uploads embeddings to Qdrant. Skips persistence entirely if the session contains no messages to avoid database clutter.
  - **`build_context(db, user_id, current_message, current_conversation)`**: Matches semantic hits from Qdrant, merges them with the recent PostgreSQL sliding-window history, and returns a deduplicated, ordered context list.

#### `app/services/planner_service.py`
- **`class PlannerService`**:
  - **`create_plan(db, user_id, message, mode, schema, model)`**: Prompts the LLM to write a Python script operating on the input DataFrame schema. Strips markdown blocks and returns parsed JSON containing the code.

#### `app/services/executor_service.py`
- **`class ExecutorService`**:
  - **Purpose**: Safely compiles and executes generated Python scripts.
  - **`execute(plan, df, mode, query, stream_callback, model)`**:
    - **Mechanism**: Instantiates a local execution scope dict (`df`, `pd`, `np`, `px`, `fig`). Compiles the generated script using `compile()` to capture precise syntax checks. Runs the script inside `exec()`. If `is_visualization` is true, it extracts the `fig` variable and returns its JSON representation; otherwise, it extracts the updated `df` and returns the top 20 records.

#### `app/services/explanation_service.py`
- **`class ExplanationService`**:
  - **`generate(message, code, model)`**: Generates a clear explanation of what the executed script accomplished.
