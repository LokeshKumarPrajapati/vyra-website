"""
Contact Manager for VYRA WhatsApp Automation
Handles contact storage, CRUD operations, and import/export
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import re


class ContactManager:
    """Manages contacts for WhatsApp automation"""

    def __init__(self, data_dir: str = "data"):
        """
        Initialize Contact Manager

        Args:
            data_dir: Directory to store contacts.json
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        self.contacts_file = self.data_dir / "contacts.json"
        self.contacts = self._load_contacts()

    def _load_contacts(self) -> List[Dict[str, Any]]:
        """Load contacts from JSON file"""
        if not self.contacts_file.exists():
            return []

        try:
            with open(self.contacts_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[ContactManager] Error loading contacts: {e}")
            return []

    def _save_contacts(self) -> bool:
        """Save contacts to JSON file"""
        try:
            with open(self.contacts_file, 'w', encoding='utf-8') as f:
                json.dump(self.contacts, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ContactManager] Error saving contacts: {e}")
            return False

    def add_contact(self, name: str, phone: Optional[str] = None,
                    email: Optional[str] = None, whatsapp_number: Optional[str] = None,
                    notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Add a new contact

        Args:
            name: Contact name (required)
            phone: Phone number
            email: Email address
            whatsapp_number: WhatsApp number (if different from phone)
            notes: Additional notes

        Returns:
            Dictionary with result and contact data
        """
        # Validate required fields
        if not name or not name.strip():
            return {'success': False, 'error': 'Name is required'}

        name = name.strip()

        # Clean and validate phone numbers
        if phone:
            phone = self._clean_phone_number(phone)
            if phone and not self._validate_phone_number(phone):
                return {'success': False, 'error': f'Invalid phone number format: {phone}'}

        if whatsapp_number:
            whatsapp_number = self._clean_phone_number(whatsapp_number)
            if whatsapp_number and not self._validate_phone_number(whatsapp_number):
                return {'success': False, 'error': f'Invalid WhatsApp number format: {whatsapp_number}'}

        # If WhatsApp number not provided, use phone number
        if not whatsapp_number and phone:
            whatsapp_number = phone

        # Check for duplicates (same name or same phone/whatsapp)
        duplicate = self._find_duplicate(name, phone, whatsapp_number)
        if duplicate:
            return {
                'success': False,
                'error': f'Contact already exists: {duplicate["name"]}',
                'existing_contact': duplicate
            }

        # Create contact object
        contact = {
            'id': self._generate_id(),
            'name': name,
            'phone': phone,
            'email': email.strip() if email else None,
            'whatsapp_number': whatsapp_number,
            'notes': notes.strip() if notes else None,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }

        self.contacts.append(contact)

        if self._save_contacts():
            return {'success': True, 'contact': contact}
        else:
            # Rollback
            self.contacts.pop()
            return {'success': False, 'error': 'Failed to save contact'}

    def get_contact(self, contact_id: str) -> Optional[Dict[str, Any]]:
        """Get contact by ID"""
        for contact in self.contacts:
            if contact.get('id') == contact_id:
                return contact
        return None

    def update_contact(self, contact_id: str, **updates) -> Dict[str, Any]:
        """
        Update an existing contact

        Args:
            contact_id: ID of contact to update
            **updates: Fields to update (name, phone, email, whatsapp_number, notes)

        Returns:
            Dictionary with result and updated contact
        """
        contact = self.get_contact(contact_id)
        if not contact:
            return {'success': False, 'error': 'Contact not found'}

        # Validate phone numbers if provided
        if 'phone' in updates and updates['phone']:
            phone = self._clean_phone_number(updates['phone'])
            if not self._validate_phone_number(phone):
                return {'success': False, 'error': f'Invalid phone number: {phone}'}
            updates['phone'] = phone

        if 'whatsapp_number' in updates and updates['whatsapp_number']:
            whatsapp = self._clean_phone_number(updates['whatsapp_number'])
            if not self._validate_phone_number(whatsapp):
                return {'success': False, 'error': f'Invalid WhatsApp number: {whatsapp}'}
            updates['whatsapp_number'] = whatsapp

        # Update fields
        for key, value in updates.items():
            if key in ['name', 'phone', 'email', 'whatsapp_number', 'notes']:
                contact[key] = value.strip() if isinstance(
                    value, str) else value

        contact['updated_at'] = datetime.now().isoformat()

        if self._save_contacts():
            return {'success': True, 'contact': contact}
        else:
            return {'success': False, 'error': 'Failed to save changes'}

    def delete_contact(self, contact_id: str) -> Dict[str, Any]:
        """Delete a contact by ID"""
        contact = self.get_contact(contact_id)
        if not contact:
            return {'success': False, 'error': 'Contact not found'}

        self.contacts = [c for c in self.contacts if c.get('id') != contact_id]

        if self._save_contacts():
            return {'success': True, 'message': f'Deleted contact: {contact["name"]}'}
        else:
            return {'success': False, 'error': 'Failed to delete contact'}

    def list_contacts(self) -> List[Dict[str, Any]]:
        """Get all contacts"""
        return self.contacts.copy()

    def search_contacts(self, query: str) -> List[Dict[str, Any]]:
        """
        Search contacts by name or phone number

        Args:
            query: Search query string

        Returns:
            List of matching contacts
        """
        query = query.lower().strip()
        results = []

        for contact in self.contacts:
            # Search in name
            if query in contact.get('name', '').lower():
                results.append(contact)
                continue

            # Search in phone
            if contact.get('phone') and query in contact['phone'].lower():
                results.append(contact)
                continue

            # Search in WhatsApp number
            if contact.get('whatsapp_number') and query in contact['whatsapp_number'].lower():
                results.append(contact)
                continue

            # Search in email
            if contact.get('email') and query in contact['email'].lower():
                results.append(contact)
                continue

        return results

    def get_contact_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get contact by exact name match (case-insensitive)"""
        name = name.lower().strip()
        for contact in self.contacts:
            if contact.get('name', '').lower() == name:
                return contact
        return None

    def get_contact_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Get contact by phone or WhatsApp number"""
        phone = self._clean_phone_number(phone)
        for contact in self.contacts:
            if contact.get('phone') == phone or contact.get('whatsapp_number') == phone:
                return contact
        return None

    def import_from_vcf(self, vcf_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Import contacts from VCF parser result

        Args:
            vcf_result: Result dictionary from vcf_parser.parse_vcf_file()

        Returns:
            Import summary with counts and errors
        """
        if not vcf_result.get('success'):
            return {
                'success': False,
                'error': vcf_result.get('error', 'VCF parsing failed'),
                'imported': 0,
                'skipped': 0,
                'errors': []
            }

        imported = 0
        skipped = 0
        errors = []

        for contact_data in vcf_result.get('contacts', []):
            result = self.add_contact(
                name=contact_data.get('name'),
                phone=contact_data.get('phone'),
                email=contact_data.get('email'),
                whatsapp_number=contact_data.get('whatsapp_number'),
                notes=contact_data.get('notes')
            )

            if result.get('success'):
                imported += 1
            else:
                skipped += 1
                errors.append(
                    f"{contact_data.get('name')}: {result.get('error')}")

        return {
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'total': imported + skipped,
            'errors': errors if errors else None
        }

    def export_to_vcf(self) -> str:
        """
        Export all contacts to VCF format string

        Returns:
            VCF formatted string
        """
        vcf_lines = []

        for contact in self.contacts:
            vcf_lines.append("BEGIN:VCARD")
            vcf_lines.append("VERSION:3.0")

            # Name
            name = contact.get('name', 'Unknown')
            vcf_lines.append(f"FN:{name}")

            # Phone
            if contact.get('phone'):
                vcf_lines.append(f"TEL;TYPE=CELL:{contact['phone']}")

            # WhatsApp (if different from phone)
            if contact.get('whatsapp_number') and contact['whatsapp_number'] != contact.get('phone'):
                vcf_lines.append(
                    f"TEL;TYPE=WHATSAPP:{contact['whatsapp_number']}")

            # Email
            if contact.get('email'):
                vcf_lines.append(f"EMAIL:{contact['email']}")

            # Notes
            if contact.get('notes'):
                vcf_lines.append(f"NOTE:{contact['notes']}")

            vcf_lines.append("END:VCARD")
            vcf_lines.append("")  # Empty line between contacts

        return '\n'.join(vcf_lines)

    def _generate_id(self) -> str:
        """Generate unique ID for contact"""
        import uuid
        return str(uuid.uuid4())

    def _clean_phone_number(self, phone: str) -> str:
        """Clean phone number by removing spaces and formatting"""
        if not phone:
            return phone

        # Remove spaces, dashes, parentheses
        phone = re.sub(r'[\s\-\(\)\.]+', '', phone)

        # Remove +91 or 91 prefix if present
        if phone.startswith('+91'):
            phone = phone[3:]
        elif phone.startswith('91') and len(phone) > 10:
            phone = phone[2:]

        # Normalize: if it's 10 digits, keep as is.
        # User requested skipping +91, implies storing as 10 digit number.

        return phone

    def _validate_phone_number(self, phone: str) -> bool:
        """Validate phone number format"""
        if not phone:
            return False

        # Allow 10-15 digits, with or without +
        pattern = r'^(\+)?\d{7,15}$'
        return bool(re.match(pattern, phone))

    def _find_duplicate(self, name: str, phone: Optional[str], whatsapp: Optional[str]) -> Optional[Dict[str, Any]]:
        """Check if contact with same name or number already exists"""
        for contact in self.contacts:
            # Check name match (case-insensitive)
            if contact.get('name', '').lower() == name.lower():
                return contact

            # Check phone/whatsapp match
            if phone and (contact.get('phone') == phone or contact.get('whatsapp_number') == phone):
                return contact

            if whatsapp and (contact.get('phone') == whatsapp or contact.get('whatsapp_number') == whatsapp):
                return contact

        return None
