import sys

file_path = "/Users/junya/.gemini/antigravity/scratch/TOPFORM_LINE_Bot/line_service.py"

with open(file_path, "r") as f:
    content = f.read()

start_marker = '        elif state == "select_date":'
end_marker = '        elif state == "select_time":'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1:
    print(f"Start marker not found: {start_marker}")
    sys.exit(1)
if end_idx == -1:
    print(f"End marker not found: {end_marker}")
    sys.exit(1)

print(f"Found block from {start_idx} to {end_idx}")

new_block = '''        elif state == "select_date":
            await self._process_select_date(reply_token, user_id, session, text, data)

'''

new_content = content[:start_idx] + new_block + content[end_idx:]

with open(file_path, "w") as f:
    f.write(new_content)

print("Successfully replaced content.")
