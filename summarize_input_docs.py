#!/usr/bin/env python3
"""
Summarization Script for Input Documents
Summarizes all PDF files in /data/input_docs and provides word counts
"""

import os
import sys
from pathlib import Path

# Try to import PDF libraries
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    from pdf2image import convert_from_path
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

# Install required packages if not available
if not HAS_PDFPLUMBER:
    print("Installing pdfplumber...")
    os.system("pip install pdfplumber -q")
    import pdfplumber
    HAS_PDFPLUMBER = True

if not HAS_PYPDF2:
    print("Installing PyPDF2...")
    os.system("pip install PyPDF2 -q")
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF using available methods."""
    text = ""
    
    # Try pdfplumber first (best for modern PDFs)
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            if text.strip():
                return text
        except Exception as e:
            print(f"  ⚠️  pdfplumber failed: {str(e)[:50]}...")
    
    # Try PyPDF2 as fallback
    if HAS_PYPDF2:
        try:
            with open(pdf_path, 'rb') as pdf_file:
                reader = PdfReader(pdf_file)
                for page_num, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            if text.strip():
                return text
        except Exception as e:
            print(f"  ⚠️  PyPDF2 failed: {str(e)[:50]}...")
    
    return text if text.strip() else "[Could not extract text]"


def summarize_text(text: str, max_sentences: int = 5) -> str:
    """Create a simple extractive summary."""
    if "[Could not extract" in text:
        return text
    
    # Split into sentences
    sentences = []
    current = ""
    for char in text:
        current += char
        if char in '.!?':
            sentences.append(current.strip())
            current = ""
    
    if current.strip():
        sentences.append(current.strip())
    
    # Remove very short sentences
    sentences = [s for s in sentences if len(s.split()) > 3]
    
    # Take first N sentences as summary
    summary_sentences = sentences[:max_sentences]
    summary = " ".join(summary_sentences)
    
    return summary if summary.strip() else text[:200] + "..."


def main():
    # Set up paths
    base_path = Path(__file__).parent
    input_dir = base_path / "data" / "input_docs"
    
    # Check if input directory exists (try alternate path)
    if not input_dir.exists():
        alt_path = Path("/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/input_docs")
        if alt_path.exists():
            input_dir = alt_path
        else:
            print(f"❌ Input directory not found at {input_dir}")
            sys.exit(1)
    
    # Find all PDF files
    pdf_files = sorted(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"❌ No PDF files found in {input_dir}")
        sys.exit(1)
    
    print(f"\n📄 Found {len(pdf_files)} PDF files\n")
    print("=" * 80)
    
    # Process each file
    file_summaries = []
    total_words = 0
    
    for pdf_path in pdf_files:
        print(f"\n📖 Processing: {pdf_path.name}")
        print("-" * 80)
        
        # Extract text
        print("   Extracting text...", end="", flush=True)
        text = extract_text_from_pdf(str(pdf_path))
        print(" ✓")
        
        # Get word count of extracted text
        extracted_word_count = count_words(text)
        print(f"   Extracted {extracted_word_count} words")
        
        # Create summary
        print("   Creating summary...", end="", flush=True)
        summary = summarize_text(text, max_sentences=6)
        print(" ✓")
        
        # Count words in summary
        summary_word_count = count_words(summary)
        print(f"   Summary: {summary_word_count} words")
        
        # Store results
        file_summaries.append({
            "file_name": pdf_path.name,
            "summary": summary,
            "summary_word_count": summary_word_count,
            "extracted_word_count": extracted_word_count
        })
        
        total_words += summary_word_count
        
        # Print first 150 chars of summary
        summary_preview = summary[:150].replace("\n", " ")
        if len(summary) > 150:
            summary_preview += "..."
        print(f"   Preview: {summary_preview}")
    
    # Print final report
    print("\n" + "=" * 80)
    print("\n📊 SUMMARIZATION REPORT")
    print("=" * 80)
    
    print(f"\nTotal Files Processed: {len(file_summaries)}")
    print(f"Total Words in All Summaries: {total_words}")
    print("\n" + "-" * 80)
    print("INDIVIDUAL FILE SUMMARIES:")
    print("-" * 80)
    
    for i, item in enumerate(file_summaries, 1):
        print(f"\n{i}. {item['file_name']}")
        print(f"   Extracted Words: {item['extracted_word_count']}")
        print(f"   Summary Word Count: {item['summary_word_count']}")
        print(f"\n   Summary:")
        print(f"   " + "\n   ".join(item['summary'].split("\n")))
    
    # Summary statistics
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"\nTotal Files: {len(file_summaries)}")
    print(f"Total Summary Words: {total_words}")
    print(f"Average Words per Summary: {total_words / len(file_summaries):.1f}")
    
    # Breakdown
    print("\nWord Count Breakdown:")
    for item in file_summaries:
        print(f"  {item['file_name']:<50} {item['summary_word_count']:>6} words")
    print(f"  {'TOTAL':<50} {total_words:>6} words")
    
    # Save results to JSON file
    import json
    output_file = base_path / "summarization_results.json"
    results = {
        "summary": {
            "total_files": len(file_summaries),
            "total_summary_words": total_words,
            "average_summary_words": round(total_words / len(file_summaries), 2)
        },
        "files": file_summaries
    }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ Results saved to {output_file}")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
