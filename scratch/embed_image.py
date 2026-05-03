import base64
import re

# Read the image
with open('static/background.jpg', 'rb') as f:
    encoded_string = base64.b64encode(f.read()).decode('utf-8')

data_uri = f"data:image/jpeg;base64,{encoded_string}"

# Read the HTML file
with open('templates/guest.html', 'r') as f:
    content = f.read()

# Replace the url('/static/background.jpg') with the data URI
content = re.sub(r"url\('/static/background\.jpg'\)", f"url('{data_uri}')", content)

# Write back
with open('templates/guest.html', 'w') as f:
    f.write(content)
print("Successfully embedded image as base64 in guest.html")
