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

prompts_second_batch = {
    "session-intelligence": "A minimalistic Apple-style app icon featuring a clean white stylized line graph or bar chart, representing data analysis and insights, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark cyan to light cyan gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "nodeflow": "A minimalistic Apple-style app icon featuring a clean white network of interconnected nodes and arrows, depicting a workflow, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark indigo to light indigo gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "code-review": "A minimalistic Apple-style app icon featuring a clean white checkmark inside a speech bubble, symbolizing code review and feedback, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark slate blue to light slate blue gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "systematic-debugging": "A minimalistic Apple-style app icon featuring a clean white stylized bug icon with a target crosshair, symbolizing systematic debugging, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark lime green to light lime green gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "content-writer": "A minimalistic Apple-style app icon featuring a clean white stylized feather quill pen over a subtle document icon, symbolizing content writing, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark sepia to light sepia gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "skill-creator": "A minimalistic Apple-style app icon featuring a clean white stylized gear icon with a sparkling star, symbolizing skill creation and development, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark gold to light gold gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "finance": "A minimalistic Apple-style app icon featuring a clean white stylized money bag icon, symbolizing finance and wealth management, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark forest green to light forest green gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "social-media-dl": "A minimalistic Apple-style app icon featuring a clean white down arrow pointing into a stylized cloud icon, symbolizing social media download, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark sky blue to light sky blue gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "webcrawl": "A minimalistic Apple-style app icon featuring a clean white stylized spider icon, symbolizing web crawling and data collection, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark grey-blue to light grey-blue gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "scheduler": "A minimalistic Apple-style app icon featuring a clean white stylized calendar icon with a small clock, symbolizing scheduling and time management, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark peach to light peach gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes."
}

for skill_name, prompt_text in prompts_second_batch.items():
    print(f"Generating icon for {skill_name}...")
    generate_icon(prompt_text, f"{skill_name}.png")
    time.sleep(0.5)
