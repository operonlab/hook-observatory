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

prompts = {
    "anvil": "A minimalistic Apple-style app icon featuring a clean white anvil icon with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark grey to light grey gradient squircle background. The anvil should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "blueprint": "A minimalistic Apple-style app icon featuring a clean white blueprint scroll or rolled-up technical drawing icon with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark teal to light teal gradient squircle background. The blueprint scroll should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "brainstorming": "A minimalistic Apple-style app icon featuring a clean white lightbulb icon with subtle radiating lines indicating ideas, a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark yellow to light yellow gradient squircle background. The lightbulb should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "capture": "A minimalistic Apple-style app icon featuring a clean white hand reaching out to catch data, represented abstractly, with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark orange to light orange gradient squircle background. The hand should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "forge": "A minimalistic Apple-style app icon featuring a clean white flame icon with an integrated gear, subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark red to light red gradient squircle background. The flame and gear should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "sentinel": "A minimalistic Apple-style app icon featuring a clean white shield icon with an integrated radar sweep or stylized eye, subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark green to light green gradient squircle background. The shield should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "memvault": "A minimalistic Apple-style app icon featuring a clean white stylized brain or abstract crystal structure icon, subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark purple to light purple gradient squircle background. The symbol should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "maestro": "A minimalistic Apple-style app icon featuring a clean white conductor's baton icon, subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark brown to light brown gradient squircle background. The baton should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes.",
    "frontend-design": "A minimalistic Apple-style app icon featuring a clean white paintbrush or pen tool icon with a small stylized cursor, subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant dark pink to light pink gradient squircle background. The symbols should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes."
}

# Generate smart-search icon again to complete the set.
# The prompt for smart-search was already provided in the previous turn.
# I will use the prompt for smart-search from previous turn again to ensure it is in the generated set.
prompts["smart-search"] = "A minimalistic Apple-style app icon featuring a clean white magnifying glass icon with a subtle 3D effect and delicate shadows, centrally placed on a smooth, vibrant deep blue to light blue gradient squircle background. The magnifying glass should occupy 50-60% of the icon's area. The overall aesthetic is sleek, modern, and easily recognizable, even at small sizes."


for skill_name, prompt_text in prompts.items():
    print(f"Generating icon for {skill_name}...")
    generate_icon(prompt_text, f"{skill_name}.png")
    time.sleep(0.5)

