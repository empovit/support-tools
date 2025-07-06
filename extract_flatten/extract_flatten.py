#!/usr/bin/env python3
"""
Archive/Directory Flattener Script

This script takes either a directory or an archive file as input and:
1. Extracts all files recursively into a flat directory structure
2. Deduplicates filenames using prepended path hashes
3. Adds .txt extension to specific file types
4. Skips empty files and OS metadata files
5. Supports popular Linux archive formats
6. Creates mapping file showing hash-to-path relationships
7. Aborts if output directory is not empty
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

    def __init__(self, source_path, output_dir, consolidate=False, max_file_size_mb=1):
        self.source_path = Path(source_path)
        self.output_dir = Path(output_dir)
        self.consolidate = consolidate
        self.max_file_size = max_file_size_mb * 1024 * 1024  # Convert MB to bytes
        self.consolidation_groups = {}  # Track files for consolidation

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

    def get_unique_filename(self, original_name, source_path_str=""):
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
            unique_filename = f"must-gather_{path_hash}_{base_name}{extension}"
            # Store mapping for later reference
            self.hash_to_path[path_hash] = source_path_str
        else:
            # For files in root directory, use original name
            unique_filename = f"must-gather_{base_name}{extension}"

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

    def _split_large_file(self, file_path):
        """Split files larger than max_file_size into smaller chunks."""
        file_path = Path(file_path)
        
        # Check if file exists and is larger than max size
        if not file_path.exists():
            return []
            
        file_size = file_path.stat().st_size
        if file_size <= self.max_file_size:
            return [file_path]  # No splitting needed
        
        print(f"Splitting large file: {file_path.name} ({file_size / (1024*1024):.1f} MB)")
        
        # Calculate number of parts needed
        num_parts = (file_size + self.max_file_size - 1) // self.max_file_size
        
        # Generate part filenames
        base_name = file_path.stem
        extension = file_path.suffix
        part_files = []
        
        # Read and split the file
        try:
            with open(file_path, 'rb') as source_file:
                for part_num in range(1, num_parts + 1):
                    part_filename = f"{base_name}.part{part_num:03d}{extension}"
                    part_path = file_path.parent / part_filename
                    
                    with open(part_path, 'wb') as part_file:
                        remaining_bytes = min(self.max_file_size, file_size - (part_num - 1) * self.max_file_size)
                        
                        # Copy data in chunks to avoid memory issues
                        bytes_written = 0
                        chunk_size = 64 * 1024  # 64KB chunks
                        
                        while bytes_written < remaining_bytes:
                            chunk_size_to_read = min(chunk_size, remaining_bytes - bytes_written)
                            chunk = source_file.read(chunk_size_to_read)
                            if not chunk:
                                break
                            part_file.write(chunk)
                            bytes_written += len(chunk)
                    
                    part_files.append(part_path)
                    print(f"  Created: {part_filename} ({part_path.stat().st_size / (1024*1024):.1f} MB)")
            
            # Remove the original large file
            file_path.unlink()
            print(f"  Removed original file: {file_path.name}")
            print(f"  Split into {num_parts} parts")
            
            return part_files
            
        except Exception as e:
            print(f"Error splitting file {file_path}: {e}")
            # Clean up any partial files created
            for part_file in part_files:
                if part_file.exists():
                    part_file.unlink()
            return [file_path]  # Return original file if splitting failed

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

    def _should_consolidate_file(self, filename):
        """Check if file should be consolidated (.log and .previous.log files)."""
        if not self.consolidate:
            return False

        return filename.lower().endswith('.log') or filename.lower().endswith('.previous.log')

    def _add_to_consolidation_group(self, file_path, source_path_str, unique_name):
        """Add file to consolidation group if applicable."""
        if not self._should_consolidate_file(file_path.name):
            return False

        # Group by directory (using hash_prefix as key)
        hash_prefix = hashlib.md5(source_path_str.encode()).hexdigest()[:8] if source_path_str else "root"

        if hash_prefix not in self.consolidation_groups:
            self.consolidation_groups[hash_prefix] = []

        self.consolidation_groups[hash_prefix].append({
            'file_path': file_path,
            'source_path_str': source_path_str,
            'unique_name': unique_name,
            'original_name': file_path.name
        })

        return True

    def _create_consolidated_files(self):
        """Create consolidated files from groups."""
        consolidated_count = 0

        for hash_prefix, files in self.consolidation_groups.items():
            if len(files) <= 1:
                # Single file, process normally
                file_info = files[0]
                dest_path = self.output_dir / file_info['unique_name']
                shutil.copy2(file_info['file_path'], dest_path)
                continue

            # Multiple files, create consolidated file
            if hash_prefix == "root":
                consolidated_name = "must-gather_CONSOLIDATED_LOGS.log.txt"
            else:
                consolidated_name = f"must-gather_{hash_prefix}_CONSOLIDATED_LOGS.log.txt"

            consolidated_path = self.output_dir / consolidated_name

            # Sort files alphabetically by their full path
            sorted_files = sorted(files, key=lambda f: f"{f['source_path_str'] or ''}/{f['original_name']}")

            # Custom sort to put .previous.log before .log for same base filename
            def sort_key(file_info):
                full_path = f"{file_info['source_path_str'] or ''}/{file_info['original_name']}"
                filename = file_info['original_name']

                # Extract base name without .log or .previous.log
                if filename.endswith('.previous.log'):
                    base_name = filename[:-len('.previous.log')]
                    priority = 0  # .previous.log comes first
                elif filename.endswith('.log'):
                    base_name = filename[:-len('.log')]
                    priority = 1  # .log comes second
                else:
                    base_name = filename
                    priority = 2  # other files come last

                return (full_path.rsplit('/', 1)[0] if '/' in full_path else '', base_name, priority)

            sorted_files = sorted(files, key=sort_key)

            # Create consolidated file
            with open(consolidated_path, 'w', encoding='utf-8', errors='replace') as consolidated_file:
                consolidated_file.write(f"# Contains {len(files)} log files:\n")
                for file_info in sorted_files:
                    full_path = f"{file_info['source_path_str']}/{file_info['original_name']}" if file_info['source_path_str'] else file_info['original_name']
                    consolidated_file.write(f"#   {full_path}\n")
                consolidated_file.write("\n" + "="*80 + "\n\n")

                for i, file_info in enumerate(sorted_files):
                    # Simple separator with full file path
                    full_path = f"{file_info['source_path_str']}/{file_info['original_name']}" if file_info['source_path_str'] else file_info['original_name']
                    consolidated_file.write(f"--- {full_path} ---\n\n")

                    try:
                        with open(file_info['file_path'], 'r', encoding='utf-8', errors='replace') as source_file:
                            content = source_file.read()
                            consolidated_file.write(content)
                    except Exception as e:
                        consolidated_file.write(f"[ERROR: Could not read file content: {e}]\n")

                    if i < len(sorted_files) - 1:  # Don't add separator after last file
                        consolidated_file.write(f"\n\n")

            # Check if consolidated file needs to be split
            split_files = self._split_large_file(consolidated_path)
            if len(split_files) > 1:
                print(f"Consolidated and split: {len(files)} log files -> {consolidated_name} ({len(split_files)} parts)")
            else:
                print(f"Consolidated: {len(files)} log files -> {consolidated_name}")
            consolidated_count += len(files)

        return consolidated_count

    def _process_single_file(self, file_path, source_dir, files_processed):
        """Process a single file - generate unique name and either copy or add to consolidation group."""
        # Get relative path for context
        rel_path = file_path.relative_to(source_dir)
        source_path_str = str(rel_path.parent) if rel_path.parent != Path('.') else ""

        # Generate unique filename
        unique_name = self.get_unique_filename(file_path.name, source_path_str)

        # Try to add to consolidation group first
        if self._add_to_consolidation_group(file_path, source_path_str, unique_name):
            print(f"Queued for consolidation: {rel_path} -> {unique_name}")
        else:
            # Process normally (copy directly)
            dest_path = self.output_dir / unique_name
            shutil.copy2(file_path, dest_path)
            
            # Check if file needs to be split
            split_files = self._split_large_file(dest_path)
            if len(split_files) > 1:
                print(f"Processed and split: {rel_path} -> {len(split_files)} parts")
            else:
                print(f"Processed: {rel_path} -> {unique_name}")

        if files_processed % 100 == 0:
            print(f"Processed {files_processed} files...")

    def process_files(self, source_dir):
        """Process all files in the source directory recursively."""
        source_dir = Path(source_dir)
        files_processed = 0
        files_skipped = 0

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
                    self._process_single_file(file_path, source_dir, files_processed + 1)
                    files_processed += 1

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    files_skipped += 1

        print(f"Processing complete: {files_processed} files processed, {files_skipped} files skipped")

        # Create consolidated files if consolidation is enabled
        consolidated_count = 0
        if self.consolidate:
            print(f"\nCreating consolidated files...")
            consolidated_count = self._create_consolidated_files()
            if consolidated_count > 0:
                print(f"Consolidated {consolidated_count} files into groups")

        # Write mapping file
        self.write_mapping_file()

        return files_processed, files_skipped, consolidated_count

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
  %(prog)s -s logs.tar.gz -o logs-flat -c  # Enable consolidation
  %(prog)s -s archive.zip -o output -m 5   # Split files larger than 5MB

Supported archive formats:
  - ZIP (.zip)
  - TAR (.tar, .tar.gz, .tar.bz2, .tar.xz, .tgz, .tbz2, .txz)
  - GZIP (.gz) - standalone compressed files
  - 7ZIP (.7z) - requires py7zr package
  - RAR (.rar) - requires rarfile package

Files with these extensions will get .txt appended:
  yaml, yml, list, log, descr, status, labels

Consolidation (-c flag):
  - Consolidates all .log and .previous.log files within each subdirectory
  - Creates files named: CONSOLIDATED_LOGS.log.txt (root) or {hash}_CONSOLIDATED_LOGS.log.txt (subdirs)
  - Files are sorted alphabetically, with .previous.log appearing before .log for same base filename
  - Each file section is separated by: --- original/path/filename ---
  - Header shows count and list of included files

Notes:
  - Output directory must be empty (script will abort if not)
  - Hash-to-path mappings are saved to .path_mappings.txt
  - File names are prefixed with 8-character path hashes for deduplication
  - OS metadata files are automatically filtered out (macOS, Windows, Linux)
  - Consolidation groups files by subdirectory for logical organization
  - Files larger than specified size will be split into smaller parts (.part001, .part002, etc.)
  - Split parts maintain the original file extension and must-gather prefix
        """
    )

    parser.add_argument('-s', '--source', required=True, metavar='SRC', help='Source directory or archive file')
    parser.add_argument('-o', '--output', required=True, metavar='OUT', help='Output directory for flattened files')
    parser.add_argument('-c', '--consolidate', action='store_true', help='Consolidate all .log and .previous.log files in each subdirectory')
    parser.add_argument('-m', '--max-size', type=int, default=1, metavar='MB', help='Maximum file size in MB before splitting (default: 1)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    return parser


def main():
    """Main function with argument parsing."""
    parser = _create_argument_parser()
    args = parser.parse_args()

    try:
        extractor = ArchiveExtractor(args.source, args.output, args.consolidate, args.max_size)
        result = extractor.run()

        # Handle different return formats for backward compatibility
        if len(result) == 3:
            processed, skipped, consolidated = result
        else:
            processed, skipped = result
            consolidated = 0

        print(f"\nSummary:")
        print(f"  Files processed: {processed}")
        print(f"  Files skipped: {skipped}")
        if consolidated > 0:
            print(f"  Files consolidated: {consolidated}")
        print(f"  Output directory: {Path(args.output).absolute()}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()