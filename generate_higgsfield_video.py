import subprocess
import json
import re

# Construct the higgsfield command as a list for subprocess.run
higgsfield_command = [
    "higgsfield", "generate", "create", "seedance_2_0",
    "--prompt", "Acme premium-biotech cinematic system. Deep forest green and warm cream palette only, single bright-green #3D9E6E accent. Anamorphic lens, shallow depth of field, soft side lighting, subtle film grain, 24fps motion, color graded toward forest-green and cream — never teal/orange, never gold, never neon. Lab, molecular, clinical, or clean product b-roll. Calm authoritative pacing, generous negative space, editorial biotech mood. No on-screen text in the generated footage. :: slow cinematic macro of a semaglutide pen injector on a dark forest surface, hands in clinical gloves gently rotating the device, soft side-lighting from left, shallow depth of field, subtle molecular helix bokeh in background, 24fps, calm deliberate movement, no text, no logos",
    "--aspect_ratio", "9:16",
    "--duration", "12",
    "--wait",
    "--json" # Request JSON output for easier parsing
]

try:
    print("Executing Higgsfield video generation...")
    # Use subprocess.run to fully block and capture output
    # `text=True` decodes stdout/stderr as text. `check=True` raises CalledProcessError on non-zero exit codes.
    result = subprocess.run(higgsfield_command, capture_output=True, text=True, check=True)
    
    higgsfield_stdout = result.stdout.strip()
    higgsfield_stderr = result.stderr.strip()

    print(f"Higgsfield Stdout:\n{higgsfield_stdout}")
    if higgsfield_stderr:
        print(f"Higgsfield Stderr:\n{higgsfield_stderr}")

    # Attempt to parse JSON from stdout.
    try:
        video_data = json.loads(higgsfield_stdout)
        media_url = video_data.get('media_url') or video_data.get('path') # Higgsfield might return 'path' for local files
        if media_url:
            print(f"H_VIDEO_OUTPUT_PATH:{media_url}") # Custom marker for parent to parse
        else:
            print(f"Error: 'media_url' or 'path' not found in Higgsfield output: {higgsfield_stdout}")
            exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not parse JSON from Higgsfield stdout. Raw output:\n{higgsfield_stdout}")
        exit(1)

except subprocess.CalledProcessError as e:
    print(f"Higgsfield command failed with exit code {e.returncode}.")
    print(f"Stdout: {e.stdout}")
    print(f"Stderr: {e.stderr}")
    exit(1)
except FileNotFoundError:
    print("Error: 'higgsfield' command not found. Ensure Higgsfield CLI is installed and in PATH.")
    exit(1)
