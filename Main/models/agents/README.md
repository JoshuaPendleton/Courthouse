# Creator-controlled Courthouse red-team model storage

Place three **different** licensed GGUF model files here, named exactly:

- `agent1.gguf`
- `agent2.gguf`
- `agent3.gguf`

Or adjust `config/agent_models.json` to match other filenames. Only the server
administrator controls these files; website visitors cannot replace them.

**There are no model weights shipped with this source export.** The models were
not supplied, and it would be inaccurate to pretend that they are. Once the
creator adds real GGUF files, the server validates and preloads the three models
on startup (unless `COURTHOUSE_PRELOAD_AGENTS=0`).

If committing weights to GitHub, use Git LFS (`git lfs install; git lfs track
"*.gguf"`), verify the model license permits redistribution, and ensure your
storage quota covers all three files. GitHub does not run inference itself.
