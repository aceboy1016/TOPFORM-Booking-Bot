import sys

file_path = "/Users/junya/.gemini/antigravity/scratch/TOPFORM_LINE_Bot/line_service.py"

with open(file_path, "r") as f:
    content = f.read()

start_marker = '    def _parse_date_query(self, text: str) -> Optional[datetime]:'
end_marker = '    def _parse_multiple_dates'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1:
    print(f"Start marker not found: {start_marker}")
    sys.exit(1)
if end_idx == -1:
    print(f"End marker not found: {end_marker}")
    sys.exit(1)

print(f"Found block from {start_idx} to {end_idx}")

new_impl = '''    def _parse_date_query(self, text: str) -> Optional[datetime]:
        """Wrapper for single date backward compatibility."""
        dates = self._parse_multiple_dates(text)
        return dates[0] if dates else None

'''

# Keep the end_marker and everything after it
new_content = content[:start_idx] + new_impl + content[end_idx:]

with open(file_path, "w") as f:
    f.write(new_content)

print("Successfully replaced content.")
