import json, sys
sys.path.insert(0, r'd:\Workspace\YouTubeSummarizer')
from core_logic import fetch_available_models
with open(r'd:\Workspace\YouTubeSummarizer\settings.json', 'r', encoding='utf-8') as fh:
    settings = json.load(fh)
models = fetch_available_models(settings['api_key'], settings['base_url'], settings.get('proxy') or None)
with open(r'd:\Workspace\YouTubeSummarizer\available_models.txt', 'w', encoding='utf-8') as out:
    out.write('\n'.join(models))
print(len(models))
