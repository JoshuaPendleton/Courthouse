# Courthouse — Three locally hosted GGUF red-team AI agents

Courthouse is a cross-platform, **locally run Python web application** for authorized red-team testing of an uploaded GGUF model. The visitor uploads **only the model being assessed**. Three independent red-team GGUF models are stored and managed **on the Courthouse server**; they are not uploaded on every visit. There is one strategy, **Red Team**.

The three real GGUF red-team models generate attack prompts in four security domains (prompt injection, confidential-data exposure, unauthorized tool use, and autonomous-agent behavior beyond approved boundaries). They exchange notes after the first test round, then produce three individual scorecards and a combined evidence-based assessment. The code does **not** use scripted AI-agent substitutes. Proposed tools are simulated and are never executed.

> **Important: GGUF model weights are NOT included in this export.** No actual model files were provided. The project includes the complete code and model-storage layout, but the creator must add three licensed, distinct GGUF files once to make the red team operational. The health screen explicitly reports missing models, rather than pretending the agents have loaded.

## Requirements

- Windows 10/11, macOS or Linux, with **Python 3.10+** and enough RAM/disk to load all three red-team weights plus the uploaded target. Using the default eager preload, peak memory can exceed the sum of the sizes of all four models, plus inference/context overhead.
- [`llama-cpp-python`](https://github.com/abetlen/llama-cpp-python), installed by the setup scripts. On some systems this native dependency needs a C++ compiler, CMake, Python development libraries, or platform-specific GPU build settings.
- Three compatible, **different** `.gguf` chat-model files with licenses permitting your intended use and distribution. If the chosen weights are not instruction-following/chat-tuned, results may be limited or skipped.
- A GGUF target model file from the visitor (8 GiB default upload limit). Native tool-call tests require the target model's chat template to support simulated tool calls; otherwise those tests are **skipped**, not marked as passed.

**No external AI model API or Ollama dependency is required.** The app is intended for a trusted local/server environment, not a public service without further hardening.

## 0. Quick start: download the recommended juror models

Model weights are not stored in Git. After cloning, download the three tested juror models (about 4.7 GiB in total) from Hugging Face into `models/agents/`:

```bash
python scripts/download_agents.py
```

On macOS/Linux use `python3`. The script uses only the Python standard library, resumes interrupted downloads, skips models already present, and checks every file against the size and SHA-256 listed in `config/agent_sources.json`. Run `python scripts/download_agents.py --check` to verify without downloading. Review each model's license on its Hugging Face page before use or redistribution.

| Juror file | Hugging Face repo | Size |
|---|---|---|
| `Hermes-3-Llama-3.2-3B-Q4_K_M.gguf` | bartowski/Hermes-3-Llama-3.2-3B-GGUF | 2.0 GB |
| `Qwen2.5-3B-Instruct-abliterated.Q4_K_M.gguf` | mradermacher/Qwen2.5-3B-Instruct-abliterated-GGUF | 1.9 GB |
| `qwen3-1.7b-jailbreak-reasoning.i1-Q4_K_M.gguf` | mradermacher/Qwen3-1.7B-Jailbreak-reasoning-i1-GGUF | 1.1 GB |

Any other distinct `.gguf` placed in `models/agents/` also becomes a juror, and each juror can be switched on or off in the web UI.

## 1. Add the three hosted red-team models (once, as creator)

Put the following files into the repository's `models/agents/` directory:

```text
Courthouse_Complete_CrossPlatform_v7/
├── models/
│   ├── agents/
│   │   ├── agent1.gguf       <- creator-supplied red-team model 1
│   │   ├── agent2.gguf       <- creator-supplied red-team model 2
│   │   └── agent3.gguf       <- creator-supplied red-team model 3
│   └── uploads/             <- visitor target uploads (NOT committed)
├── config/agent_models.json <- which model filename belongs to which agent
├── local_engine.py          <- model validation, preloading and local inference
├── courthouse.py            <- three real LLM agents and assessment scoring
├── server.py                <- local web server and API
├── static/                  <- website HTML, CSS and JS
├── tests/                   <- cross-platform software unit tests
├── run_windows.bat
├── install_dependencies_windows.bat
├── run.sh
├── install_dependencies.sh
├── Makefile
├── Dockerfile
├── compose.yaml
└── .github/workflows/ci.yml
```

You can rename these files, but update `config/agent_models.json` to match. All filenames must refer to files directly within `models/agents/`; directory traversal and symlink escapes are blocked. Each GGUF must have a valid `GGUF` header, and the agent files must have **different SHA-256 hashes**. The uploaded target must also differ from all three hosted agent files.

Run `python scripts/check_agents.py` (or `python3 ...`) for a quick file-presence check. This script is a file checker, **not an AI red-team test**.

### Commit your hosted weights to GitHub (optional)

This project includes `.gitattributes` configured for **Git LFS** (`*.gguf`). If the model licenses and your repository's LFS storage/size limits permit:

```bash
git lfs install
git add models/agents/agent1.gguf models/agents/agent2.gguf models/agents/agent3.gguf
git add .gitattributes config/agent_models.json
git commit -m "Add licensed Courthouse red-team GGUF models"
git push
```

Collaborators should run `git lfs install` and `git lfs pull` after cloning. **GitHub stores files; it does not run a persistent inference server.** A local computer or deployed compute server must run this app. For large/private models, it is often preferable to keep model weights off GitHub and place them on the actual Courthouse host instead. `models/uploads/` is always ignored so visitor-submitted target models are not committed.

## 2. Install and start

### Windows

1. Install Python 3.10 or later, including the `py` launcher.
2. Double-click `install_dependencies_windows.bat`.
3. Add the three GGUF files to `models\\agents\\`.
4. Double-click `run_windows.bat`.
5. Open <http://127.0.0.1:8050>.

### macOS / Linux

```bash
chmod +x install_dependencies.sh run.sh
./install_dependencies.sh
# Add the three red-team GGUF files to models/agents/
./run.sh
```

Open <http://127.0.0.1:8050>. You can also run `make setup`, `make run`, or `make test` on systems with `make` installed.

### Docker (CPU-only development option)

With the three weights present locally:

```bash
docker compose up --build
```

The Docker Compose configuration mounts `models/agents` as read-only, persists uploaded targets in `models/uploads`, and exposes the service **only on localhost port 8050**. Building native inference packages and loading four models takes significant CPU time and memory. GPU acceleration needs additional platform-specific configuration.

## 3. What happens when Courthouse starts

1. `server.py` invokes `initialize_hosted_agents()`.
2. `local_engine.py` reads `config/agent_models.json` and validates each configured GGUF file.
3. The three models are registered with permanent server-side IDs and checked for distinct weights.
4. By default (`COURTHOUSE_PRELOAD_AGENTS=1`) all three are loaded into `llama-cpp-python` **before the server starts accepting assessments**. This needs substantial RAM. Startup will show model-loading errors if the files or runtime are unavailable.
5. When a user opens the website, `/api/health` reports which agents are loaded/ready. The three cards show their status. **The Run button remains unavailable** until the three hosted models are ready.
6. The user submits **one target GGUF** to `/api/upload`; the target is loaded for local inference and the three server-hosted models generate attacks and reports.

If the hosted files aren't present, the server still serves the setup UI and health diagnostics, but **cannot run an assessment**. Fix the files/dependencies and restart the server. The app never substitutes scripted tests in place of missing AI models.

### Configuration

Environment variables are documented in `.env.example`. Set them before running; the app does not automatically load `.env` files. Common options:

| Variable | Default | Meaning |
|---|---|---|
| `COURTHOUSE_PRELOAD_AGENTS` | `1` | `1` = load all three hosted models at startup; `0` = validate now, load on first use |
| `COURTHOUSE_MAX_LOADED` | `4` | Maximum cached model instances (3 hosted + 1 target by default) |
| `COURTHOUSE_N_CTX` | `8192` | Local inference context length |
| `COURTHOUSE_GPU_LAYERS` | `0` | Number of llama.cpp GPU layers (hardware-dependent) |
| `COURTHOUSE_PORT` | `8050` | Local HTTP port |
| `COURTHOUSE_HOST` | `127.0.0.1` | Bind only to the local workstation by default |
| `COURTHOUSE_MAX_MODEL_BYTES` | `8589934592` | Maximum target-model upload size in bytes |
| `COURTHOUSE_AGENTS_CONFIG` | `config/agent_models.json` | Optional custom manifest path |

Setting `COURTHOUSE_PRELOAD_AGENTS=0` allows operation on some memory-constrained systems, but the agents will **not be initialized until first use**; the UI clearly indicates this distinction. Reducing the model cache below four may repeatedly unload/reload weights and slow the assessment.

## 4. Developer tests and CI

Run from the project root:

```bash
python -m unittest discover -s tests -v
```

The test suite uses mock model outputs **only to check application wiring, file validation, reporting, and integration**. Mock responses are never used as live red-team agents. `.github/workflows/ci.yml` runs the tests on Windows, macOS and Linux. Native inference of actual model weights requires local integration testing with your chosen GGUF files.

## Security and deployment limitations

- **Local prototype only.** This server has no user accounts, rate limiting, model isolation, or persistent security audit DB. Never expose it directly to the public internet as-is.
- Loading third-party GGUF models invokes native inference code; process uploaded targets only in hardened containers/VMs if operating as a service for untrusted users.
- The website's upload transfers the target file to the **Courthouse host**. If run on a remote machine, the target is sent to that machine; it does not stay on the uploader's workstation. Use authenticated HTTPS and explicit retention/deletion policies before any shared deployment.
- Assessment evidence uses synthetic secrets and inert tools. Scoring reflects only observed behavior in this limited test, not an industry certification.
- Some GGUF chat templates do not support simulated tool-call messages. These are reported as untested/skipped, not as passes.
- Three different weight files are required; different filenames alone are not enough.

## License

No project-wide redistribution license is provided. Keep your source-code licensing and each downloaded model's redistribution/license terms separate.
