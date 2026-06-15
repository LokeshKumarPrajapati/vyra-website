const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');

const vcfPath = path.join(__dirname, 'contacts.vcf');

if (!fs.existsSync(vcfPath)) {
    console.error(`VCF file not found at ${vcfPath}`);
    process.exit(1);
}

const vcfContent = fs.readFileSync(vcfPath, 'utf8');

// Split by BEGIN:VCARD to get individual cards
// Note: The file might start with content before the first BEGIN:VCARD, so filter empty
const cards = vcfContent.split('BEGIN:VCARD');

console.log(`Found ${cards.length - 1} contacts to process.`);

let successCount = 0;
let failCount = 0;

for (const card of cards) {
    if (!card.trim()) continue;

    const lines = card.split(/\r?\n/);
    let givenName = '';
    let familyName = '';
    let phones = [];
    let emails = [];
    let fn = '';

    for (let line of lines) {
        line = line.trim();
        if (line.startsWith('N:')) {
            // N:Family;Given;Middle;Prefix;Suffix
            const parts = line.substring(2).split(';');
            familyName = parts[0] || '';
            givenName = parts[1] || '';
        } else if (line.startsWith('FN:')) {
            fn = line.substring(3);
        } else if (line.startsWith('TEL')) {
            // TEL;type=CELL;type=VOICE;type=pref:+917903352211
            // or TEL;type=pref:+91 7321-959379
            const parts = line.split(':');
            if (parts.length > 1) {
                let p = parts.slice(1).join(':').trim();
                // Strip +91 or 91 if it starts with it and has enough digits
                if (p.startsWith('+91')) {
                    p = p.substring(3).trim();
                } else if (p.startsWith('91') && p.length > 10) {
                    p = p.substring(2).trim();
                }
                phones.push(p);
            }
        } else if (line.startsWith('EMAIL')) {
            const parts = line.split(':');
            if (parts.length > 1) {
                emails.push(parts.slice(1).join(':').trim());
            }
        }
    }

    // Fallback for names
    if (!givenName && fn) {
        const nameParts = fn.split(' ');
        if (nameParts.length > 1) {
            givenName = nameParts.slice(0, -1).join(' ');
            familyName = nameParts[nameParts.length - 1];
        } else {
            givenName = fn;
        }
    }

    if (!givenName) {
        // Skip if no name found (or use a placeholder?)
        // Helper to check if useful info exists
        if (phones.length === 0 && emails.length === 0) continue;
        givenName = 'Unknown';
    }

    // cleaning up names
    givenName = givenName.replace(/"/g, '\\"');
    familyName = familyName.replace(/"/g, '\\"');

    // Construct command
    // gog contacts create --given="G" --family="F" --phone="P" --email="E" --no-input

    // We can only pass one phone and email via flags for now based on help
    const phoneArg = phones.length > 0 ? `--phone="${phones[0]}"` : '';
    const emailArg = emails.length > 0 ? `--email="${emails[0]}"` : '';

    // If multiple phones/emails, we might miss them. 
    // But for now let's stick to primary one as CLI limitations might exist.

    if (!phoneArg && !emailArg) {
        // Skip if no contact info
        console.log(`Skipping ${givenName} ${familyName}: No phone or email.`);
        continue;
    }

    const command = `gog contacts create --given="${givenName}" --family="${familyName}" ${phoneArg} ${emailArg} --no-input`;

    try {
        console.log(`Importing: ${givenName} ${familyName}...`);
        execSync(command, { stdio: 'pipe' }); // stdio pipe to avoid spamming output but capture err
        successCount++;
    } catch (error) {
        console.error(`Failed to import ${givenName} ${familyName}: ${error.message}`);
        failCount++;
    }
}

console.log(`Import completed. Success: ${successCount}, Failed: ${failCount}`);
