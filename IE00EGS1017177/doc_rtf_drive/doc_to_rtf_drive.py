#!/usr/bin/env python3
"""
Convert DOC/DOCX files to RTF using Google Drive API.

This script finds all DOC/DOCX files in the folder structure and converts them
to RTF format using Google Drive API, maintaining the same folder structure so 
that the RTF files can be processed by convert.py without folder structure changes.

Requirements:
  - Internet connection
  - Google Drive API credentials (credentials.json)
  - Google Drive API enabled in Google Cloud Console

Usage:
    # Use default path (searches all subdirectories)
    python doc_to_rtf.py
    
    # Or specify custom path
    python doc_to_rtf.py --input-dir /path/to/source
    
    # Filter by IE ID within the input directory
    python doc_to_rtf.py --ie-id IE1KG4884
"""

import sys
import os
import io
import logging
import argparse
import mimetypes
import time
import json
import random
import ssl
from pathlib import Path
from typing import List, Tuple

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import MediaIoBaseDownload

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Ensure stdout is unbuffered
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# Add script directory to path for venv_utils
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

# Ensure virtual environment is activated (for any dependencies that might need it)
try:
    from venv_utils import ensure_venv_activated
    ensure_venv_activated()
except ImportError:
    # venv_utils not available, skip activation
    pass

# Google Drive API scopes
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Default input directory
DEFAULT_INPUT_DIR = Path("/Users/tenzinmonlam/Documents/dharmaduta/file_convert_3/IE00EGS1017177/sources")

# Supported file extensions
SUPPORTED_EXTENSIONS = {'.doc', '.docx'}

# Retry configuration
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1  # seconds
RETRY_BACKOFF_MULTIPLIER = 2


def get_credentials():
    """Get valid user credentials from storage or prompt for authorization."""
    creds = None
    
    # Check if token.json exists
    token_path = Path(__file__).parent / "token.json"
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials_path = Path(__file__).parent / "credentials.json"
            if not credentials_path.exists():
                logger.error(f"credentials.json not found at {credentials_path}")
                logger.error("Please download credentials.json from Google Cloud Console")
                sys.exit(1)
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    
    return creds




def find_doc_files(input_dir: Path, ie_id: str = None) -> List[Path]:
    """
    Recursively find all DOC/DOCX files in the input directory and all subdirectories.
    
    Args:
        input_dir: Directory to search (searches all subdirectories recursively)
        ie_id: Optional IE ID to filter (if None, searches all subdirectories)
    
    Returns:
        List of Path objects for DOC/DOCX files
    """
    doc_files = []
    
    if ie_id:
        # Search in specific IE folder
        ie_folder = input_dir / ie_id
        if not ie_folder.exists():
            logger.warning(f"Folder not found: {ie_folder}")
            return doc_files
        search_dir = ie_folder
    else:
        search_dir = input_dir
    
    # Use rglob to recursively search all subdirectories
    for ext in SUPPORTED_EXTENSIONS:
        # Case-insensitive search - rglob searches all subdirectories
        doc_files.extend(search_dir.rglob(f"*{ext}"))
        doc_files.extend(search_dir.rglob(f"*{ext.upper()}"))
    
    # Remove duplicates and sort
    doc_files = sorted(set(doc_files))
    
    logger.info(f"Searching in: {search_dir}")
    logger.info(f"Recursive search enabled - checking all subdirectories")
    
    return doc_files


def convert_doc_to_rtf(service, doc_path: Path, output_path: Path) -> Tuple[bool, str]:
    """
    Convert a single DOC/DOCX file to RTF using Google Drive API with retry logic.
    
    Args:
        service: Google Drive API service object
        doc_path: Path to the DOC/DOCX file
        output_path: Path where RTF file should be saved
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Retry loop with exponential backoff
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            # Determine MIME type
            mime_type = mimetypes.guess_type(str(doc_path))[0]
            if not mime_type:
                if doc_path.suffix.lower() == '.doc':
                    mime_type = "application/msword"
                elif doc_path.suffix.lower() == '.docx':
                    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                else:
                    return False, f"Unknown file type: {doc_path.suffix}"
            
            # Get file size
            file_size_mb = doc_path.stat().st_size / (1024 * 1024)
            
            # Create file metadata
            file_metadata = {
                "name": doc_path.stem,
                "mimeType": "application/vnd.google-apps.document"
            }
            
            # Upload file to Google Drive - ALWAYS use resumable uploads
            if attempt > 0:
                logger.info(f"  Retry {attempt}/{MAX_RETRIES-1}: Uploading {doc_path.name} ({file_size_mb:.2f} MB)...")
            else:
                logger.info(f"  Uploading {doc_path.name} ({file_size_mb:.2f} MB)...")
            
            # Use resumable upload for ALL files (handles network problems better)
            media = MediaFileUpload(
                str(doc_path),
                mimetype=mime_type,
                resumable=True
            )
            
            file = (
                service.files()
                .create(body=file_metadata, media_body=media, fields="id")
                .execute()
            )
            
            file_id = file.get('id')
            logger.info(f"  File ID: {file_id}")
            
            # Export as RTF
            # For files > 1MB, use exportLinks method to bypass 10MB export limit
            # For smaller files, try regular export first (faster), fall back to exportLinks if needed
            use_export_links = file_size_mb > 1.0
            
            if use_export_links:
                logger.info(f"  Using exportLinks method (file size: {file_size_mb:.2f} MB)")
                # Get exportLinks from file metadata
                file_info = service.files().get(
                    fileId=file_id,
                    fields="exportLinks"
                ).execute()
                
                export_links = file_info.get("exportLinks", {})
                rtf_url = export_links.get("application/rtf")
                
                if not rtf_url:
                    # Clean up uploaded file
                    service.files().delete(fileId=file_id).execute()
                    return False, "RTF export link unavailable"
                
                # Download RTF file directly via HTTP GET
                creds = service._http.credentials
                headers = {"Authorization": f"Bearer {creds.token}"}
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with requests.get(rtf_url, headers=headers, stream=True, timeout=300) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    
                    with open(output_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    progress = (downloaded / total_size) * 100
                                    logger.info(f"  Download {int(progress)}%")
            else:
                # Try regular export method for smaller files (faster)
                try:
                    logger.info(f"  Using regular export method (file size: {file_size_mb:.2f} MB)")
                    request = service.files().export_media(
                        fileId=file_id,
                        mimeType="application/rtf"
                    )
                    
                    file_buffer = io.BytesIO()
                    downloader = MediaIoBaseDownload(file_buffer, request)
                    done = False
                    
                    while not done:
                        status, done = downloader.next_chunk()
                        if status:
                            logger.info(f"  Download {int(status.progress() * 100)}%")
                    
                    # Write RTF file
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(file_buffer.getvalue())
                        
                except HttpError as export_error:
                    # If regular export fails (e.g., export > 10MB), fall back to exportLinks
                    error_code = export_error.resp.status if hasattr(export_error, 'resp') else None
                    if error_code == 403 or "export" in str(export_error).lower():
                        logger.info(f"  Regular export failed, falling back to exportLinks method...")
                        # Get exportLinks from file metadata
                        file_info = service.files().get(
                            fileId=file_id,
                            fields="exportLinks"
                        ).execute()
                        
                        export_links = file_info.get("exportLinks", {})
                        rtf_url = export_links.get("application/rtf")
                        
                        if not rtf_url:
                            # Clean up uploaded file
                            service.files().delete(fileId=file_id).execute()
                            return False, "RTF export link unavailable"
                        
                        # Download RTF file directly via HTTP GET
                        creds = service._http.credentials
                        headers = {"Authorization": f"Bearer {creds.token}"}
                        
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        with requests.get(rtf_url, headers=headers, stream=True, timeout=300) as response:
                            response.raise_for_status()
                            total_size = int(response.headers.get('content-length', 0))
                            downloaded = 0
                            
                            with open(output_path, "wb") as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        if total_size > 0:
                                            progress = (downloaded / total_size) * 100
                                            logger.info(f"  Download {int(progress)}%")
                    else:
                        # Re-raise if it's not a size-related error
                        raise
            
            # Clean up uploaded file from Google Drive
            try:
                service.files().delete(fileId=file_id).execute()
            except HttpError as e:
                logger.warning(f"  Could not delete temporary file from Drive: {e}")
            
            return True, f"Converted successfully to {output_path}"
            
        except (HttpError, requests.exceptions.RequestException, IOError, OSError, ssl.SSLError) as error:
            last_error = error
            error_msg = str(error)
            
            # Check if this is a retryable error
            is_retryable = True
            if isinstance(error, HttpError):
                # Don't retry on 4xx errors (client errors) except 429 (rate limit)
                status_code = error.resp.status if hasattr(error, 'resp') else None
                if status_code and 400 <= status_code < 500 and status_code != 429:
                    is_retryable = False
            elif isinstance(error, (ssl.SSLError, requests.exceptions.SSLError)):
                # SSL errors are always retryable (network issues)
                is_retryable = True
            elif isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
                # Timeouts and connection errors are retryable
                is_retryable = True
            
            if not is_retryable or attempt == MAX_RETRIES - 1:
                # Last attempt or non-retryable error
                if isinstance(error, HttpError):
                    return False, f"Google Drive API error: {error_msg}"
                else:
                    return False, f"Error: {error_msg}"
            
            # Calculate delay for next retry (exponential backoff with jitter)
            delay = INITIAL_RETRY_DELAY * (RETRY_BACKOFF_MULTIPLIER ** attempt)
            jitter = random.uniform(0, 1)  # Add random jitter to avoid thundering herd
            delay += jitter
            logger.warning(f"  Upload failed (attempt {attempt + 1}/{MAX_RETRIES}): {error_msg}")
            logger.info(f"  Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            
        except Exception as e:
            # Non-retryable errors (e.g., file not found, invalid format)
            return False, f"Error: {str(e)}"
    
    # Should not reach here, but just in case
    return False, f"Failed after {MAX_RETRIES} attempts: {last_error}"




def main():
    parser = argparse.ArgumentParser(
        description="Convert DOC/DOCX files to RTF using Google Drive API. "
                    "Maintains folder structure for compatibility with convert.py"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Input directory to search recursively for DOC/DOCX files (default: {DEFAULT_INPUT_DIR})"
    )
    parser.add_argument(
        "--ie-id",
        type=str,
        default=None,
        help="Process only this specific IE collection (e.g., IE1KG4884)"
    )
    parser.add_argument(
        "--output-suffix",
        type=str,
        default=".rtf",
        help="Output file suffix (default: .rtf)"
    )
    parser.add_argument(
        "--remove-original",
        action="store_true",
        help="Remove original DOC files after successful conversion (default: False, keeps original files)"
    )
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        logger.error(f"Input directory not found: {args.input_dir}")
        sys.exit(1)
    
    logger.info("=" * 70)
    logger.info("DOC TO RTF CONVERTER (Google Drive API)")
    logger.info("=" * 70)
    logger.info(f"Input directory: {args.input_dir}")
    logger.info(f"IE ID filter: {args.ie_id or 'All'}")
    logger.info("Processing mode: Sequential (one file at a time)")
    logger.info("=" * 70)
    
    # Authenticate with Google Drive API
    logger.info("Authenticating with Google Drive API...")
    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)
    logger.info("Authentication successful!")
    
    # Find DOC files
    logger.info(f"\nSearching for DOC/DOCX files in {args.input_dir}...")
    doc_files = find_doc_files(args.input_dir, args.ie_id)
    
    if not doc_files:
        logger.warning("No DOC/DOCX files found!")
        return
    
    logger.info(f"Found {len(doc_files)} DOC/DOCX files")
    logger.info("=" * 70)
    
    # Prepare files to process (skip if RTF already exists)
    files_to_process = []
    skipped_count = 0
    
    for doc_path in doc_files:
        # Create output path: same location, change extension to .rtf
        output_path = doc_path.with_suffix(args.output_suffix)
        
        # Skip if RTF already exists
        if output_path.exists():
            skipped_count += 1
            continue
        
        files_to_process.append((doc_path, output_path))
    
    if skipped_count > 0:
        logger.info(f"Skipping {skipped_count} files (RTF already exists)")
    
    if not files_to_process:
        logger.info("All files already converted!")
        return
    
    total_files = len(files_to_process)
    logger.info(f"Converting {total_files} files (one at a time)...")
    logger.info("=" * 70)
    
    # Process files one by one sequentially
    total_success = 0
    total_failed = 0
    errors = []
    
    for file_num, (doc_path, output_path) in enumerate(files_to_process, 1):
        logger.info(f"\n[{file_num}/{total_files}] Processing {doc_path.name}...")
        
        try:
            # Convert using Google Drive API
            success, message = convert_doc_to_rtf(service, doc_path, output_path)
            
            if success:
                total_success += 1
                logger.info(f"[OK] {doc_path.name}")
            else:
                total_failed += 1
                logger.error(f"[FAIL] {doc_path.name}: {message}")
                errors.append({
                    "file": str(doc_path),
                    "error": message
                })
        except Exception as e:
            total_failed += 1
            error_msg = str(e)
            logger.error(f"[FAIL] {doc_path.name}: {error_msg}")
            errors.append({
                "file": str(doc_path),
                "error": error_msg
            })
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total files to process: {total_files}")
    logger.info(f"Success: {total_success}")
    logger.info(f"Failed: {total_failed}")
    if skipped_count > 0:
        logger.info(f"Skipped (already converted): {skipped_count}")
    
    if errors:
        logger.info("\nErrors:")
        for error in errors[:10]:  # Show first 10 errors
            logger.error(f"  - {Path(error['file']).name}: {error['error']}")
        if len(errors) > 10:
            logger.info(f"  ... and {len(errors) - 10} more errors")
        
        # Save failed files to a JSON file for retry later
        failed_files_path = Path(__file__).parent / "failed_files.json"
        failed_files = [{"file": error["file"], "error": error["error"]} for error in errors]
        try:
            with open(failed_files_path, "w") as f:
                json.dump(failed_files, f, indent=2)
            logger.info(f"\nFailed files saved to: {failed_files_path}")
            logger.info("You can retry these files by running the script again (it will skip successful conversions)")
        except Exception as e:
            logger.warning(f"Could not save failed files list: {e}")
    
    logger.info("=" * 70)
    
    # Optionally remove original DOC files (only if --remove-original flag is set)
    if args.remove_original and total_success > 0:
        logger.info("\nRemoving original DOC files...")
        removed_count = 0
        for doc_path, output_path in files_to_process:
            if output_path.exists() and doc_path.exists():
                try:
                    doc_path.unlink()
                    removed_count += 1
                except Exception as e:
                    logger.warning(f"Could not remove {doc_path.name}: {e}")
        logger.info(f"Removed {removed_count} original DOC files")
    elif total_success > 0:
        logger.info(f"\nOriginal DOC files preserved ({total_success} files kept)")


if __name__ == "__main__":
    main()