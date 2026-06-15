"""
VCF (vCard) Parser Utility for VYRA Contact Management
Parses vCard files (versions 2.1, 3.0, 4.0) and extracts contact information
"""

import vobject
from typing import Dict, Any, Optional
import re


def parse_vcf_file(file_path: str) -> Dict[str, Any]:
    """
    Parse a VCF/vCard file and extract contact information

    Args:
        file_path: Path to the VCF file

    Returns:
        Dictionary with parsing results including list of contacts
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            vcf_content = f.read()

        return parse_vcf_content(vcf_content)

    except UnicodeDecodeError:
        # Try with different encoding
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                vcf_content = f.read()
            return parse_vcf_content(vcf_content)
        except Exception as e:
            return {
                'success': False,
                'error': f'Encoding error: {str(e)}',
                'contacts': []
            }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'contacts': []
        }


def parse_vcf_content(vcf_content: str) -> Dict[str, Any]:
    """
    Parse VCF content string and extract contacts

    Args:
        vcf_content: String content of VCF file

    Returns:
        Dictionary with parsing results
    """
    contacts = []
    errors = []

    try:
        # Split multiple vCards if present
        vcard_blocks = []

        # vobject can handle multiple vCards in one file
        # We'll try to parse them one by one
        current_block = []
        for line in vcf_content.split('\n'):
            current_block.append(line)
            if line.strip().upper() == 'END:VCARD':
                vcard_blocks.append('\n'.join(current_block))
                current_block = []

        # If there are remaining lines, add them
        if current_block:
            remaining = '\n'.join(current_block).strip()
            if remaining:
                vcard_blocks.append(remaining)

        # Parse each vCard block
        for idx, vcard_text in enumerate(vcard_blocks):
            if not vcard_text.strip():
                continue

            try:
                vcard = vobject.readOne(vcard_text)
                contact = extract_contact_info(vcard)
                if contact:
                    contacts.append(contact)
            except Exception as e:
                error_msg = f"Error parsing vCard {idx + 1}: {str(e)}"
                errors.append(error_msg)
                print(f"[VCF Parser] {error_msg}")
                continue

        success = len(contacts) > 0
        summary = f"Parsed {len(contacts)} contact(s) from VCF file"

        if errors:
            summary += f" ({len(errors)} error(s))"

        return {
            'success': success,
            'contacts': contacts,
            'summary': summary,
            'errors': errors if errors else None,
            'type': 'vcf'
        }

    except Exception as e:
        return {
            'success': False,
            'error': f'Failed to parse VCF: {str(e)}',
            'contacts': [],
            'type': 'vcf'
        }


def extract_contact_info(vcard: Any) -> Optional[Dict[str, Any]]:
    """
    Extract contact information from a vCard object

    Args:
        vcard: vobject vCard object

    Returns:
        Dictionary with contact information or None if invalid
    """
    contact = {}

    # Extract name
    name = None
    if hasattr(vcard, 'fn'):
        name = vcard.fn.value.strip()
    elif hasattr(vcard, 'n'):
        # Construct name from N field (Family;Given;Middle;Prefix;Suffix)
        n_parts = []
        if hasattr(vcard.n.value, 'given') and vcard.n.value.given:
            n_parts.append(vcard.n.value.given)
        if hasattr(vcard.n.value, 'family') and vcard.n.value.family:
            n_parts.append(vcard.n.value.family)
        name = ' '.join(n_parts).strip()

    if not name:
        # Skip contacts without a name
        return None

    contact['name'] = name

    # Extract phone numbers
    phones = []
    whatsapp_number = None

    if hasattr(vcard, 'tel_list'):
        for tel in vcard.tel_list:
            phone_value = tel.value.strip()
            if phone_value:
                # Clean phone number (remove spaces, dashes, parentheses)
                cleaned_phone = clean_phone_number(phone_value)
                phones.append(cleaned_phone)

                # Check if it's marked as WhatsApp or if it's a mobile number
                if hasattr(tel, 'params'):
                    tel_type = str(tel.params.get('TYPE', [])).lower()
                    if 'whatsapp' in tel_type or 'cell' in tel_type or 'mobile' in tel_type:
                        if not whatsapp_number:
                            whatsapp_number = cleaned_phone

    # Use first phone as default
    contact['phone'] = phones[0] if phones else None

    # If no WhatsApp number detected, use first mobile/cell number or first phone
    if not whatsapp_number and phones:
        whatsapp_number = phones[0]

    contact['whatsapp_number'] = whatsapp_number

    # Extract email
    emails = []
    if hasattr(vcard, 'email_list'):
        for email in vcard.email_list:
            email_value = email.value.strip()
            if email_value:
                emails.append(email_value)

    contact['email'] = emails[0] if emails else None

    # Extract notes
    notes = None
    if hasattr(vcard, 'note'):
        notes = vcard.note.value.strip()

    contact['notes'] = notes

    return contact


def clean_phone_number(phone: str) -> str:
    """
    Clean and format phone number

    Args:
        phone: Raw phone number string

    Returns:
        Cleaned phone number
    """
    # Remove common separators
    phone = re.sub(r'[\s\-\(\)\.]+', '', phone)

    # Ensure it starts with + for international format
    if not phone.startswith('+') and phone:
        # If it starts with digits, add + prefix
        if phone[0].isdigit():
            phone = '+' + phone

    return phone


def validate_vcf_file(file_path: str) -> bool:
    """
    Quick validation to check if file is a valid VCF

    Args:
        file_path: Path to file

    Returns:
        True if file appears to be VCF format
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            first_lines = f.read(500)

        # Check for vCard markers
        return 'BEGIN:VCARD' in first_lines.upper()

    except Exception:
        return False
