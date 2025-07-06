#!/bin/bash

# Activate the virtual environment for extract_flatten
echo "Activating virtual environment for extract_flatten..."
source venv/bin/activate

echo "Virtual environment activated!"
echo ""
echo "You can now run the script with full archive support:"
echo "  python extract_flatten.py -s source_path -o output_path"
echo "  python extract_flatten.py -s source_path -o output_path -m 5  # Split files > 5MB"
echo ""
echo "Supported formats: ZIP, TAR, GZIP, 7ZIP (.7z), RAR (.rar)"
echo "Features: must-gather prefixes, file splitting, log consolidation"
echo "Use 'python extract_flatten.py --help' for more information"
echo ""
echo "To deactivate the virtual environment, type: deactivate" 