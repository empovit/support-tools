#!/bin/bash
# Setup script for support-tools

set -e

echo "🔧 Support Tools Setup"
echo "====================="
echo

# Check Python version
python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python version: $python_version"

if [[ $(echo "$python_version 3.6" | awk '{print ($1 >= $2)}') == 1 ]]; then
    echo "✓ Python version requirement met (3.6+)"
else
    echo "❌ Python 3.6+ required, found $python_version"
    exit 1
fi

echo

# Test basic functionality
echo "Testing basic functionality..."
if python3 extract_flatten.py --help > /dev/null 2>&1; then
    echo "✓ extract_flatten.py basic test passed"
else
    echo "❌ extract_flatten.py basic test failed"
    exit 1
fi

echo

# Ask about optional dependencies
echo "Optional dependencies for extended format support:"
echo "  - py7zr: Enables 7ZIP (.7z) support"
echo "  - rarfile: Enables RAR (.rar) support"
echo

read -p "Install optional dependencies? (y/n): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Installing optional dependencies..."
    if command -v pip3 &> /dev/null; then
        pip3 install -r requirements.txt
        echo "✓ Optional dependencies installed"
    else
        echo "❌ pip3 not found. Please install manually:"
        echo "   pip install py7zr rarfile"
    fi
else
    echo "⚠️  Skipping optional dependencies"
    echo "   ZIP, TAR, and GZIP formats will work"
    echo "   7ZIP and RAR will show installation instructions if used"
fi

echo
echo "🎉 Setup complete!"
echo
echo "Usage examples:"
echo "  ./extract_flatten.py -s archive.zip -o output"
echo "  python3 extract_flatten.py -s directory -o flattened"
echo
echo "For full documentation, see README.md"