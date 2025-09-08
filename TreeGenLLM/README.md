# Tree Gen LLM

A Blender add-on that generates procedural tree models from **natural language prompts** using Geometry Nodes.  
Branches, trunk, and leaves are estimated by a lightweight LLM, and all key parameters remain adjustable through sliders after generation.

---

## Features

- **Natural Language → Geometry Nodes**  
  Describe a tree in plain language (e.g., *"a tall pine with sparse leaves"*) and generate instantly.
- **Real-time adjustment**  
  Fine-tune trunk length, branch angles, and leaf density with sliders.
- **Undo/Redo supported**  
  Safe experimentation workflow.
- **Few-shot + retry mechanism**  
  Ensures valid parameters even if inference fails.
- **Open Source (MIT License)**

---

## Requirements

- Blender **4.3.0 or newer**
- Windows, macOS, or Linux
- CPU (works) / GPU (optional, via llama.cpp)
- Internet connection (for model auto-download)

---

## Installation

1. **Download & Install**
   - Download this repository.
   - Zip the `treegen_llm/` folder.
   - In Blender: `Edit > Preferences > Add-ons > Install...` → choose the ZIP.

2. **Enable the Add-on**
   - Search for **Tree Gen LLM** in the add-ons list and enable it.

3. **Model Setup**
   - Online: Press **Setup** in `Preferences > Add-ons > Tree Gen LLM` to auto-download the required GGUF model from Hugging Face.
   - Offline: Place the GGUF file manually into the `models/` folder, then press **Refresh Model Path**.

---

## Usage

1. Open the **3D View > Sidebar (N)** → **Tree Gen LLM** panel.
2. Enter a prompt.  
   Example:  
   - *“A broadleaf tree with dense leaves”*  
   - *“Sparse branches, leaning upwards”*
3. Click **Generate**.  
   - A procedural tree mesh will appear in the viewport.
4. Adjust parameters with the sliders for trunk, branches, and leaves.
5. Use **Reset** to delete the generated tree and start over.

---

## Folder Structure

