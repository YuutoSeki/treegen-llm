# Tree Gen LLM

A Blender add-on that generates procedural trees from **natural language prompts** using Geometry Nodes and a lightweight LLM. 🌳✨

![demo](docs/demo.gif)

---

## Features

- **Natural Language → Geometry Nodes**  
  Example: *"A tall pine with sparse leaves"* → instantly generates a procedural tree.
- **Real-time adjustment UI**  
  After generation, fine-tune trunk length, branch angles, leaf density, etc. with sliders.
- **Undo/Redo supported**  
  Safe experimentation workflow.
- **Few-shot + retry mechanism**  
  Ensures valid socket values even if inference fails.
- **Open Source (MIT License)**

---

## Requirements

- Blender **4.3.0+**  
- Windows / macOS / Linux  
- CPU (works) or GPU (optional, via llama.cpp)  
- Internet connection (for first model download)  

---

## Installation

1. **Download**  
   - Grab the latest release ZIP from the [Releases page](https://github.com/YuutoSeki/treegen-llm/releases).

2. **Install in Blender**  
   - Open Blender → `Edit > Preferences > Add-ons > Install...`  
   - Select the ZIP → Enable **Tree Gen LLM**.

3. **Model setup**  
   - Online: In `Preferences > Add-ons > Tree Gen LLM`, press **Setup** to auto-download the required model from Hugging Face.  
   - Offline: Place the GGUF file into `/models/` and press **Refresh Model Path**.

---

## Usage

1. Open the **3D View > Sidebar (N) > Tree Gen LLM** panel.  
2. Enter a prompt, e.g.:  
   - *“A broadleaf tree with dense leaves”*  
   - *“Sparse branches, leaning upwards”*  
3. Click **Generate** → a procedural tree mesh will appear in the viewport.  
4. Adjust parameters (trunk, branches, leaves) with the sliders.  
5. Use **Reset** to delete the current tree and start over.  
6. Press **Cancel** if you need to stop an ongoing inference.  

---

## Folder Structure

```
treegen-llm/
 ├── __init__.py            # Main add-on code
 ├── custom_defaults.py     # Default socket values
 ├── user_socket_schema.py  # Geometry Nodes socket schema
 ├── blender_manifest.toml  # Dependencies (wheels, permissions)
 ├── manifest.json          # Required model definition (Qwen2.5-7B)
 ├── TreeNodeGen.blend      # Geometry Nodes template
 ├── models/                # GGUF model folder (user provides/downloads)
 └── wheels/                # Bundled wheels (llama-cpp-python, numpy, etc.)
```

---

## License

MIT License — free for both personal and commercial use.

---

## Acknowledgements

- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)  
- [Hugging Face Hub](https://huggingface.co)  
- Blender Geometry Nodes community  

---

## Feedback

Found a bug or have a feature request?  
👉 Please open an [Issue](https://github.com/YuutoSeki/treegen-llm/issues).  
Stars ⭐ and feedback are greatly appreciated!
