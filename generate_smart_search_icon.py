import urllib.request, json, os, base64, time

api_key = os.environ["XAI_API_KEY"]
url = "https://api.x.ai/v1/images/generations"

def generate_icon(prompt, filename):
    data = json.dumps({
        "model": "grok-imagine-image",
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json"
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    })
    resp = urllib.request.urlopen(req, timeout=60)
    result = json.loads(resp.read())
    img_data = base64.b64decode(result["data"][0]["b64_json"])
    path = os.path.expanduser(f"~/workshop/outputs/skill-icons/{filename}")
    with open(path, "wb") as f:
        f.write(img_data)
    print(f"OK: {filename} ({len(img_data)//1024}KB)")

prompt_smart_search = "A minimalistic Apple-style app icon featuring a clean white magnifying glass icon with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant deep blue to light blue gradient squircle background. The magnifying glass should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes."
generate_icon(prompt_smart_search, "smart-search.png")
time.sleep(0.5)
