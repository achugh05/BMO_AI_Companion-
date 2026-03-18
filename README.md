Setup: 
1. Install Python 3.14
2. Open project folder
3. Run:
   python -m venv .venv
   .\.venv\Scripts\activate

   pip install -r requirements.txt

   Ollama create json_llama_bmo -f ./Modelfile

   install en_US-libritts_r-medium.onnx and en_US-libritts_r-medium.onnx.json from piper_tts github 

To test CV: 

   python .\study_focus_imx500\test_focus_dashboard.py

To test bmo: 
   cd llm
   python bmo_companion.py