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

    def __init__(self, source_path, output_dir, consolidate=False):
        self.source_path = Path(source_path)
        self.output_dir = Path(output_dir)
        self.consolidate = consolidate
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

        self.path_to_prefix = {}  # Track source path to ordered prefix mapping
        self.prefix_to_path = {}  # Track ordered prefix to source path mapping (for mapping file)
        self.used_filenames = set()  # Track used filenames to prevent conflicts
        self.root_prefix = "00"  # Default root prefix, will be updated during directory mapping

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

    def _build_directory_mapping(self, source_dir):
        """Pre-scan directories and build ordered prefix mapping, excluding metadata directories."""
        source_dir = Path(source_dir)

        # Collect all unique directory paths, excluding metadata directories
        dir_paths = set()
        skipped_dirs = set()
        for file_path in source_dir.rglob('*'):
            if file_path.is_file():
                rel_path = file_path.relative_to(source_dir)
                dir_path_str = str(rel_path.parent) if rel_path.parent != Path('.') else ""
                if dir_path_str:
                    # Use shared metadata detection logic
                    path_parts = dir_path_str.split('/')
                    if self._is_metadata_path(path_parts):
                        skipped_dirs.add(dir_path_str)
                    else:
                        dir_paths.add(dir_path_str)

        if skipped_dirs:
            print(f"Skipping {len(skipped_dirs)} metadata directories: {', '.join(sorted(skipped_dirs))}")

        # Sort directory paths alphabetically
        sorted_dirs = sorted(dir_paths)

        # Create ordered prefix mapping with zero-padded numbers
        max_digits = max(2, len(str(len(sorted_dirs))))  # At least 2 digits, more if needed

        for i, dir_path in enumerate(sorted_dirs, 1):  # Start from 1
            prefix = str(i).zfill(max_digits)
            self.path_to_prefix[dir_path] = prefix
            self.prefix_to_path[prefix] = dir_path

        # Add root directory mapping for completeness in mapping file
        root_prefix = "0".zfill(max_digits)
        self.prefix_to_path[root_prefix] = "(root directory)"

        # Store the root prefix format for use in filename generation
        self.root_prefix = root_prefix

        print(f"Built directory mapping for {len(sorted_dirs)} directories")
        print(f"  {root_prefix} -> (root directory)")
        for dir_path in sorted_dirs:
            prefix = self.path_to_prefix[dir_path]
            print(f"  {prefix} -> {dir_path}")

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
        """Generate a unique filename using prepended ordered prefix for deduplication."""
        base_name = Path(original_name).stem
        extension = Path(original_name).suffix

        # Add .txt to specific extensions
        if extension.lower() in self.TXT_EXTENSIONS:
            extension += '.txt'

        # Create filename with prepended ordered prefix for deduplication
        if source_path_str and source_path_str in self.path_to_prefix:
            # Use ordered prefix to maintain alphabetical directory ordering
            prefix = self.path_to_prefix[source_path_str]
            base_filename = f"{prefix}_{base_name}{extension}"
        else:
            # For files in root directory, use "0" prefix to ensure they come first
            base_filename = f"{self.root_prefix}_{base_name}{extension}"

        # Resolve conflicts by adding counter suffix if needed
        unique_filename = self._resolve_filename_conflict(base_filename)
        return unique_filename

    def _resolve_filename_conflict(self, proposed_filename):
        """Resolve filename conflicts by adding a counter suffix."""
        if proposed_filename not in self.used_filenames:
            self.used_filenames.add(proposed_filename)
            return proposed_filename

        # Extract base name and extension for conflict resolution
        path_obj = Path(proposed_filename)
        base_name = path_obj.stem
        extension = path_obj.suffix

        # Try adding counter suffixes until we find an unused name
        counter = 1
        while True:
            conflict_filename = f"{base_name}_{counter:03d}{extension}"
            if conflict_filename not in self.used_filenames:
                self.used_filenames.add(conflict_filename)
                return conflict_filename
            counter += 1

    def write_mapping_file(self):
        """Write prefix-to-path mapping to auxiliary file."""
        # Ensure root directory mapping is always included
        if self.root_prefix not in self.prefix_to_path:
            self.prefix_to_path[self.root_prefix] = "(root directory)"

        if not self.prefix_to_path:
            return

        mapping_file = self.output_dir / ".path_mappings.txt"

        with open(mapping_file, 'w', encoding='utf-8') as f:
            f.write("# PREFIX -> SOURCE_PATH\n\n")

            # Write ALL mappings to file (no truncation) - sorted by prefix to maintain directory order
            for prefix, source_path in sorted(self.prefix_to_path.items()):
                f.write(f"{prefix} -> {source_path}\n")

        print(f"\nPath mapping written to: {mapping_file} (contains all {len(self.prefix_to_path)} mappings)")

        # Also print all mappings to console
        print("\nPrefix to Path Mappings:")
        for prefix, source_path in sorted(self.prefix_to_path.items()):
            print(f"  {prefix} -> {source_path}")

    def _is_metadata_path(self, path_parts):
        """Check if path contains metadata directories or files that should be skipped."""
        # Skip macOS metadata paths
        if '__MACOSX' in path_parts:
            return True

        # Skip Windows recycle bin paths
        if '$RECYCLE.BIN' in path_parts:
            return True

        # Skip any path component that starts with common metadata patterns
        for part in path_parts:
            if part.startswith('._'):  # AppleDouble files/directories
                return True
            if part in {'.Trashes', '.fseventsd', '.Spotlight-V100', '.TemporaryItems'}:
                return True

        return False

    def _should_skip_file(self, file_path):
        """Check if file should be skipped (e.g., empty files, OS metadata files)."""
        # Skip empty files
        if file_path.stat().st_size == 0:
            return True

        # Get the file name and path components for checking
        file_name = file_path.name
        path_parts = file_path.parts

        # Check for metadata paths using shared logic
        if self._is_metadata_path(path_parts):
            return True

        # Skip common system files
        system_files = {'.DS_Store', '.Trashes', '.fseventsd', '.Spotlight-V100', '.TemporaryItems',
                       'Thumbs.db', 'desktop.ini', '.directory'}
        if file_name in system_files:
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

        # Group by directory (using ordered prefix as key)
        group_key = self.path_to_prefix.get(source_path_str, "root") if source_path_str else "root"

        if group_key not in self.consolidation_groups:
            self.consolidation_groups[group_key] = []

        self.consolidation_groups[group_key].append({
            'file_path': file_path,
            'source_path_str': source_path_str,
            'unique_name': unique_name,
            'original_name': file_path.name
        })

        return True

    def _create_consolidated_files(self):
        """Create consolidated files from groups."""
        consolidated_count = 0

        for group_key, files in self.consolidation_groups.items():
            if len(files) <= 1:
                # Single file, process normally
                file_info = files[0]
                dest_path = self.output_dir / file_info['unique_name']
                shutil.copy2(file_info['file_path'], dest_path)
                continue

            # Multiple files, create consolidated file
            if group_key == "root":
                consolidated_name = "CONSOLIDATED_LOGS.log.txt"
            else:
                consolidated_name = f"{group_key}_CONSOLIDATED_LOGS.log.txt"

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

        # Build directory mapping first to preserve alphabetical order
        self._build_directory_mapping(source_dir)

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
  - Creates files named: CONSOLIDATED_LOGS.log.txt (root) or {prefix}_CONSOLIDATED_LOGS.log.txt (subdirs)
  - Files are sorted alphabetically, with .previous.log appearing before .log for same base filename
  - Each file section is separated by: --- original/path/filename ---
  - Header shows count and list of included files

Notes:
  - Output directory must be empty (script will abort if not)
  - Prefix-to-path mappings are saved to .path_mappings.txt
  - File names are prefixed with ordered numbers to preserve directory order
  - OS metadata files are automatically filtered out (macOS, Windows, Linux)
  - Consolidation groups files by subdirectory for logical organization
        """
    )

    parser.add_argument('-s', '--source', required=True, metavar='SRC', help='Source directory or archive file')
    parser.add_argument('-o', '--output', required=True, metavar='OUT', help='Output directory for flattened files')
    parser.add_argument('-c', '--consolidate', action='store_true', help='Consolidate all .log and .previous.log files in each subdirectory')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    return parser


def main():
    """Main function with argument parsing."""
    parser = _create_argument_parser()
    args = parser.parse_args()

    try:
        extractor = ArchiveExtractor(args.source, args.output, args.consolidate)
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