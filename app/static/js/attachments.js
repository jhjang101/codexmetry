// Limits (Matches standard business settings)
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
const MAX_FILES = 10;

// --- 1. NEW FILES LOGIC (Accumulation & Removal) ---
let stagedFiles = new DataTransfer(); // Our "Source of Truth" in RAM

function stageFiles(files) {
    const container = document.getElementById('new-files-container');
    const submitter = document.getElementById('file-submitter');
    const picker = document.getElementById('file-picker');

    if (stagedFiles.files.length + files.length > MAX_FILES) {
        alert(`Limit ${MAX_FILES} files.`);
        picker.value = ''; 
        return;
    }

    Array.from(files).forEach(file => {
        if (file.size > MAX_FILE_SIZE) {
            alert(`${file.name} is too large. Max size is 5MB.`);
            return;
        }
        
        // Prevent duplicates
        let isDuplicate = false;
        for (let i = 0; i < stagedFiles.files.length; i++) {
            if (stagedFiles.files[i].name === file.name && stagedFiles.files[i].size === file.size) {
                isDuplicate = true;
            }
        }

        const fileKey = 'f' + Math.random().toString(36).substring(2, 10);

        // Add to UI
        if (!isDuplicate) {
            stagedFiles.items.add(file);
            const row = document.createElement('div');
            row.id = 'staged-' + fileKey;
            row.className = "flex justify-between items-center bg-green-50 p-1 rounded-lg border border-green-200 text-[11px] text-green-700 font-bold mb-1";
            row.innerHTML = `
                <span class="truncate"><i class="fa-solid fa-file-circle-plus mr-1"></i>${file.name}</span>
                <button type="button" onclick="removeFromStage('${fileKey}', '${file.name.replace(/'/g, "\\'")}')" class="text-green-800 hover:text-red-600 transition-colors">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            `;
            container.appendChild(row);
        }
    });

    // 1. Sync our memory to the hidden SUBMITTER
    submitter.files = stagedFiles.files;

    // 2. WIPE the PICKER (Safe because it's not holding our real data)
    // This allows you to select the same file immediately after deleting it
    picker.value = '';

    console.log("Submitter now has:", submitter.files.length, "files");
}

function removeFromStage(fileKey, fileName) {
    const submitter = document.getElementById('file-submitter');
    const row = document.getElementById('staged-' + fileKey);
    if(row) row.remove();

    // Rebuild the Source of Truth
    const newDT = new DataTransfer();
    for (let i = 0; i < stagedFiles.files.length; i++) {
        const file = stagedFiles.files[i];
        if (file.name !== fileName) {
            newDT.items.add(file);
        }
    }
    stagedFiles = newDT;
    
    // Sync the Submitter again
    submitter.files = stagedFiles.files;
    console.log("After remove, Submitter has:", submitter.files.length);
}

// --- 2. EXISTING FILES LOGIC (Mark for Delete) ---
function toggleFileDelete(id) {
    const row = document.getElementById('existing-file-' + id);
    const input = document.getElementById('delete-input-' + id);
    const icon = document.getElementById('icon-' + id);

    if (input.disabled) {
        // ACTION: Mark for Deletion
        input.disabled = false; // Now it WILL be sent to Python
        row.classList.add('opacity-50', 'line-through', 'bg-red-50', 'border-red-200', 'text-red-700');
        row.classList.remove('bg-gray-100');
        icon.classList.replace('fa-trash-can', 'fa-rotate-left');
        icon.parentElement.title = "Undo delete";
    } else {
        // ACTION: Undo Mark
        input.disabled = true; // Now it will be IGNORED by Python
        row.classList.remove('opacity-50', 'line-through', 'bg-red-50', 'border-red-200', 'text-red-700');
        row.classList.add('bg-gray-100');
        icon.classList.replace('fa-rotate-left', 'fa-trash-can');
        icon.parentElement.title = "Delete file";
    }
}

// --- 3. DRAG AND DROP HANDLERS ---
function initAttachmentZone() {
    const dz = document.getElementById('dropzone');
    if (!dz) return;

    // Reset the RAM tracker for a fresh form
    stagedFiles = new DataTransfer();

    // 1. Prevent default browser behavior (opening the file)
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(name => {
        dz.addEventListener(name, e => {
            e.preventDefault();
            e.stopPropagation();
        });
    });

    // 2. Add visual feedback on hover
    ['dragenter', 'dragover'].forEach(name => {
        dz.addEventListener(name, () => dz.classList.add('bg-blue-100', 'border-blue-500'));
    });

    ['dragleave', 'drop'].forEach(name => {
        dz.addEventListener(name, () => dz.classList.remove('bg-blue-100', 'border-blue-500'));
    });

    // 3. Handle the actual drop
    dz.addEventListener('drop', e => {
        stageFiles(e.dataTransfer.files);
    });
}