#!/usr/bin/env python3
"""
This tool extracts files from a must-gather archive or directory structure
into a single, flat directory, and changes the extension of common manifest
and log files to .txt so they can be used with AI tools.

BASIC USAGE:
    python extract_flatten.py -s input.zip -o output_folder
    python extract_flatten.py -s /path/to/directory -o flattened_files

The output directory must be empty to prevent accidental overwrites.
Run with --help for detailed options and examples.

More information: https://github.com/empovit/support-tools/tree/main/extract_flatten
"""

import sys
import shutil
import argparse
import tempfile
import zipfile
import tarfile
import gzip
import hashlib
from pathlib import Path

# Try to import optional libraries for additional archive support
try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False

try:
    import rarfile
    HAS_RAR = True
except ImportError:
    HAS_RAR = False


class ArchiveExtractor:
    """Handles extraction and flattening of archives and directories."""

    # Extensions that should get .txt appended
    TXT_EXTENSIONS = {'.yaml', '.yml', '.list', '.log', '.descr', '.status', '.labels'}

    def __init__(self, source_path, output_dir):
        self.source_path = Path(source_path)
        self.output_dir = Path(output_dir)

        # Check if output directory exists and is not empty
        if self.output_dir.exists():
            # Check if directory is not empty
            try:
                next(self.output_dir.iterdir())
                # If we get here, directory is not empty
                raise ValueError(f"Output directory is not empty: {self.output_dir}\n"
                               f"Please use an empty directory or remove existing files.")
            except StopIteration:
                # Directory is empty, we can proceed
                pass
        else:
            # Create the directory
            self.output_dir.mkdir(parents=True, exist_ok=True)

        self.hash_to_path = {}  # Track hash to source path mapping

    def is_archive(self, path):
        """Check if the given path is a supported archive format."""
        path = Path(path)
        suffix_lower = path.suffix.lower()

        # Check for compound extensions like .tar.gz
        if len(path.suffixes) >= 2:
            compound = ''.join(path.suffixes[-2:]).lower()
            if compound in {'.tar.gz', '.tar.bz2', '.tar.xz'}:
                return True

        # Check single extensions
        archive_extensions = {'.zip', '.tar', '.tgz', '.tbz2', '.txz', '.gz', '.7z', '.rar'}
        return suffix_lower in archive_extensions

    def _extract_zip(self, archive_path, temp_dir):
        """Extract ZIP archive."""
        with zipfile.ZipFile(archive_path, 'r') as zf:
            zf.extractall(temp_dir)

    def _extract_tar(self, archive_path, temp_dir):
        """Extract TAR archive (including compressed variants)."""
        with tarfile.open(archive_path, 'r:*') as tf:
            tf.extractall(temp_dir)

    def _extract_7z(self, archive_path, temp_dir):
        """Extract 7ZIP archive."""
        if HAS_7Z:
            with py7zr.SevenZipFile(archive_path, mode='r') as szf:
                szf.extractall(temp_dir)
        else:
            raise ValueError(f"7ZIP support requires the 'py7zr' library. Install with: pip install py7zr")

    def _extract_rar(self, archive_path, temp_dir):
        """Extract RAR archive."""
        if HAS_RAR:
            with rarfile.RarFile(archive_path, 'r') as rf:
                rf.extractall(temp_dir)
        else:
            raise ValueError(f"RAR support requires the 'rarfile' library. Install with: pip install rarfile")

    def _extract_gz(self, archive_path, temp_dir):
        """Extract standalone GZIP file."""
        # Handle standalone .gz files (not .tar.gz which is handled above)
        decompressed_name = archive_path.stem  # Remove .gz extension
        decompressed_path = Path(temp_dir) / decompressed_name

        with gzip.open(str(archive_path), 'rb') as gz_file:
            with open(decompressed_path, 'wb') as out_file:
                shutil.copyfileobj(gz_file, out_file)

        # Check if the decompressed file is another archive
        if self.is_archive(decompressed_path):
            # Recursively extract the decompressed archive
            nested_temp_dir = Path(temp_dir) / "nested"
            nested_temp_dir.mkdir(exist_ok=True)
            self.extract_archive(decompressed_path, nested_temp_dir)
            # Remove the intermediate decompressed file
            decompressed_path.unlink()

    def extract_archive(self, archive_path, temp_dir):
        """Extract archive to temporary directory."""
        archive_path = Path(archive_path)
        suffix_lower = archive_path.suffix.lower()

        # Handle compound extensions
        if len(archive_path.suffixes) >= 2:
            compound = ''.join(archive_path.suffixes[-2:]).lower()
            if compound in {'.tar.gz', '.tar.bz2', '.tar.xz'}:
                suffix_lower = compound

        print(f"Extracting {archive_path.name}...")

        try:
            if suffix_lower == '.zip':
                self._extract_zip(archive_path, temp_dir)
            elif suffix_lower in {'.tar', '.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2', '.txz'}:
                self._extract_tar(archive_path, temp_dir)
            elif suffix_lower == '.7z':
                self._extract_7z(archive_path, temp_dir)
            elif suffix_lower == '.rar':
                self._extract_rar(archive_path, temp_dir)
            elif suffix_lower == '.gz':
                self._extract_gz(archive_path, temp_dir)
            else:
                raise ValueError(f"Unsupported archive format: {suffix_lower}")

        except Exception as e:
            print(f"Error extracting {archive_path}: {e}")
            raise

    def get_unique_filename(self, original_name, source_path_str="", part_num=None):
        """Generate a unique filename using prepended path hash for deduplication."""
        base_name = Path(original_name).stem
        extension = Path(original_name).suffix

        # Add .txt to specific extensions
        if extension.lower() in self.TXT_EXTENSIONS:
            extension += '.txt'

        # Create filename with prepended path hash for deduplication
        if source_path_str:
            # Include hash of the source path for uniqueness (prepended)
            path_hash = hashlib.md5(source_path_str.encode()).hexdigest()[:8]
            if part_num is not None:
                unique_filename = f"{path_hash}_{base_name}_part{part_num}{extension}"
            else:
                unique_filename = f"{path_hash}_{base_name}{extension}"
            # Store mapping for later reference
            self.hash_to_path[path_hash] = source_path_str
        else:
            # For files in root directory, use original name
            if part_num is not None:
                unique_filename = f"{base_name}_part{part_num}{extension}"
            else:
                unique_filename = f"{base_name}{extension}"

        return unique_filename

    def write_mapping_file(self):
        """Write hash-to-path mapping to auxiliary file."""
        if not self.hash_to_path:
            return

        mapping_file = self.output_dir / ".path_mappings.txt"

        with open(mapping_file, 'w', encoding='utf-8') as f:
            f.write("# Hash to Source Path Mapping\n")
            f.write("# Generated by extract_flatten.py\n")
            f.write("# Format: HASH -> SOURCE_PATH\n\n")

            for path_hash, source_path in sorted(self.hash_to_path.items()):
                f.write(f"{path_hash} -> {source_path}\n")

        print(f"\nPath mapping written to: {mapping_file}")

        # Also print the mappings to console
        print("\nHash to Path Mappings:")
        for path_hash, source_path in sorted(self.hash_to_path.items()):
            print(f"  {path_hash} -> {source_path}")

    def _should_skip_file(self, file_path):
        """Check if file should be skipped (e.g., empty files, OS metadata files)."""
        # Skip empty files
        if file_path.stat().st_size == 0:
            return True

        # Get the file name and path components for checking
        file_name = file_path.name
        path_parts = file_path.parts

        # Skip macOS metadata files
        if '__MACOSX' in path_parts:
            return True

        # Skip AppleDouble files (resource forks)
        if file_name.startswith('._'):
            return True

        # Skip common macOS system files
        macos_files = {'.DS_Store', '.Trashes', '.fseventsd', '.Spotlight-V100', '.TemporaryItems'}
        if file_name in macos_files:
            return True

        # Skip Windows system files
        windows_files = {'Thumbs.db', 'desktop.ini', '$RECYCLE.BIN'}
        if file_name in windows_files:
            return True

        # Skip Linux system files
        if file_name == '.directory':  # KDE folder settings
            return True

        return False

    def _split_large_file(self, file_path, source_dir, max_chunk_size=3 * 1024 * 1024):
        """Split a large file into chunks using line boundaries."""
        rel_path = file_path.relative_to(source_dir)
        source_path_str = str(rel_path.parent) if rel_path.parent != Path('.') else ""

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                part_num = 1
                current_chunk_size = 0
                current_chunk_lines = []

                for line in f:
                    line_size = len(line.encode('utf-8'))

                    # If adding this line would exceed the chunk size and we have lines in current chunk
                    if current_chunk_size + line_size > max_chunk_size and current_chunk_lines:
                        # Write current chunk
                        unique_name = self.get_unique_filename(file_path.name, source_path_str, part_num)
                        dest_path = self.output_dir / unique_name

                        with open(dest_path, 'w', encoding='utf-8') as chunk_file:
                            chunk_file.writelines(current_chunk_lines)

                        print(f"Processed chunk {part_num}: {rel_path} -> {unique_name} ({current_chunk_size:,} bytes)")

                        # Reset for next chunk
                        part_num += 1
                        current_chunk_lines = [line]
                        current_chunk_size = line_size
                    else:
                        # Add line to current chunk
                        current_chunk_lines.append(line)
                        current_chunk_size += line_size

                # Write the final chunk if there are remaining lines
                if current_chunk_lines:
                    unique_name = self.get_unique_filename(file_path.name, source_path_str, part_num)
                    dest_path = self.output_dir / unique_name

                    with open(dest_path, 'w', encoding='utf-8') as chunk_file:
                        chunk_file.writelines(current_chunk_lines)

                    print(f"Processed chunk {part_num}: {rel_path} -> {unique_name} ({current_chunk_size:,} bytes)")

                return part_num  # Return number of chunks created

        except (UnicodeDecodeError, Exception):
            # File cannot be split by line boundaries, return None to indicate failure
            return None

    def _process_single_file(self, file_path, source_dir, files_processed):
        """Process a single file - generate unique name and copy to output directory.

        Returns:
            bool: True if the file was split into chunks, False if copied as whole file
        """
        # Get relative path for context
        rel_path = file_path.relative_to(source_dir)
        source_path_str = str(rel_path.parent) if rel_path.parent != Path('.') else ""

        # Check file size
        file_size = file_path.stat().st_size
        max_chunk_size = 3 * 1024 * 1024  # 3 MB

        if file_size > max_chunk_size:
            # Split large files into chunks
            print(f"File {rel_path} is {file_size:,} bytes, splitting into chunks...")
            num_chunks = self._split_large_file(file_path, source_dir, max_chunk_size)

            if num_chunks is None:
                # File cannot be split by line boundaries, copy entire file with warning
                print(f"WARNING: Cannot split {rel_path} by line boundaries - copying entire file ({file_size:,} bytes)")
                unique_name = self.get_unique_filename(file_path.name, source_path_str)
                dest_path = self.output_dir / unique_name
                shutil.copy2(file_path, dest_path)
                print(f"Processed (unsplit): {rel_path} -> {unique_name}")
                return False  # File was not split
            else:
                print(f"Split {rel_path} into {num_chunks} chunks")
                return True  # File was split
        else:
            # Generate unique filename
            unique_name = self.get_unique_filename(file_path.name, source_path_str)

            # Copy file to output directory
            dest_path = self.output_dir / unique_name
            shutil.copy2(file_path, dest_path)
            print(f"Processed: {rel_path} -> {unique_name}")
            return False  # File was not split

    def process_files(self, source_dir):
        """Process all files in the source directory recursively."""
        source_dir = Path(source_dir)
        files_processed = 0
        files_skipped = 0
        files_split = 0

        print(f"Processing files from {source_dir}...")
        print(f"Recursively scanning all subdirectories...")

        # Use rglob to recursively find all files in subdirectories
        for file_path in source_dir.rglob('*'):
            if file_path.is_file():
                try:
                    # Skip empty files
                    if self._should_skip_file(file_path):
                        files_skipped += 1
                        print(f"Skipping empty file: {file_path.relative_to(source_dir)}")
                        continue

                    # Process the file
                    was_split = self._process_single_file(file_path, source_dir, files_processed + 1)
                    files_processed += 1
                    if was_split:
                        files_split += 1

                    if files_processed % 100 == 0:
                        print(f"Processed {files_processed} files...")

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    files_skipped += 1

        print(f"Processing complete: {files_processed} files processed, {files_skipped} files skipped, {files_split} files split")

        # Write mapping file
        self.write_mapping_file()

        return files_processed, files_skipped, files_split

    def run(self):
        """Main execution method."""
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {self.source_path}")

        if self.source_path.is_dir():
            print(f"Processing directory: {self.source_path}")
            return self.process_files(self.source_path)

        elif self.is_archive(self.source_path):
            print(f"Processing archive: {self.source_path}")

            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                self.extract_archive(self.source_path, temp_dir)
                return self.process_files(temp_dir)
        else:
            raise ValueError(f"Source is neither a directory nor a supported archive: {self.source_path}")


def _create_argument_parser():
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract and flatten archives or directories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -s /path/to/archive.zip -o output_dir
  %(prog)s -s /path/to/directory -o output_dir
  %(prog)s --source archive.tar.gz --output ./extracted
  %(prog)s -s ~/docs -o ./flattened -v

Supported archive formats:
  - ZIP (.zip)
  - TAR (.tar, .tar.gz, .tar.bz2, .tar.xz, .tgz, .tbz2, .txz)
  - GZIP (.gz) - standalone compressed files
  - 7ZIP (.7z) - requires py7zr package
  - RAR (.rar) - requires rarfile package

Files with these extensions will get .txt appended:
  yaml, yml, list, log, descr, status, labels

Notes:
  - Output directory must be empty (script will abort if not)
  - Hash-to-path mappings are saved to .path_mappings.txt
  - File names are prefixed with 8-character path hashes for deduplication
  - OS metadata files are automatically filtered out (macOS, Windows, Linux)
        """
    )

    parser.add_argument('-s', '--source', required=True, metavar='SRC', help='Source directory or archive file')
    parser.add_argument('-o', '--output', required=True, metavar='OUT', help='Output directory for flattened files')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    return parser


def main():
    """Main function with argument parsing."""
    parser = _create_argument_parser()
    args = parser.parse_args()

    try:
        extractor = ArchiveExtractor(args.source, args.output)
        processed, skipped, split = extractor.run()

        print(f"\nSummary:")
        print(f"  Files processed: {processed}")
        print(f"  Files skipped: {skipped}")
        print(f"  Files split: {split}")
        print(f"  Output directory: {Path(args.output).absolute()}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()