# URA Context Folder Structure Guide

**Purpose:** Organize context documents with versioned snapshots  
**Created:** January 14, 2026  
**Philosophy:** Latest working docs + dated archives for history  

---

## 📂 RECOMMENDED STRUCTURE

```
Room Appliance Integration/
│
├── Context Snapshots/
│   │
│   ├── Latest/                          🟢 ACTIVE WORKING DIRECTORY
│   │   ├── ROADMAP_v9.md               ✅ Updated Jan 14, 2026
│   │   ├── VISION_v7.md                ✅ Stable (no changes needed)
│   │   ├── PLANNING_v3_5_0.md          ✅ New (Camera Intelligence)
│   │   ├── PLANNING_v3_4_0.md          ✅ Current
│   │   ├── PLANNING_v3_6_0.md          ✅ Current
│   │   ├── QUALITY_CONTEXT.md          ✅ Current
│   │   ├── CURRENT_STATE.md            ✅ New (status snapshot)
│   │   └── README.md                   ⚠️  Minor update needed
│   │
│   └── Archive/                         📦 HISTORICAL SNAPSHOTS
│       │
│       ├── 2026-01-14/                 (Pre-v3.5.0 planning)
│       │   ├── ROADMAP_v8.md           (Superseded by v9)
│       │   ├── PLANNING_v3_3_0.md      (v3.3.0 original)
│       │   ├── PLANNING_v3_3_0_REVISED.md
│       │   ├── MULTI_SESSION_STRATEGY.md
│       │   └── README.md               (Context package docs)
│       │
│       ├── 2026-01-04/                 (Previous snapshot)
│       │   ├── ROADMAP_v7.md
│       │   ├── VISION_v6.md
│       │   └── [other v7 docs...]
│       │
│       └── 2025-12-20/                 (Earlier snapshot)
│           └── [earlier versions...]
│
├── 3.2.9/                              💾 PRODUCTION CODE (current)
│   └── [all source files...]
│
├── 3.3.0/                              (Will be created when built)
│
├── 3.5.0/                              (Will be created when built)
│
└── [other version folders...]
```

---

## 🎯 FOLDER PURPOSES

### Latest/ (Active Working Directory)

**What Goes Here:**
- Current versions of all planning/context documents
- Most recent ROADMAP
- Most recent VISION
- Active PLANNING documents (for upcoming versions)
- Quality context and standards
- Current state snapshot

**When to Update:**
- After completing a major version (roadmap update)
- When creating new planning documents
- After architectural changes
- When bugs/patterns are discovered
- When best practices evolve

**Naming Convention:**
- DOCUMENT_NAME_vN.md (version number in filename)
- Example: ROADMAP_v9.md, VISION_v7.md
- CURRENT_STATE.md (always current, no version number)

### Archive/YYYY-MM-DD/ (Historical Snapshots)

**What Goes Here:**
- Superseded versions of documents
- Historical planning documents
- Old session strategy docs
- Previous roadmaps
- Anything replaced in Latest/

**When to Archive:**
- Before updating a document in Latest/
- After a major version deployment
- When resequencing/restructuring happens
- When planning documents are superseded

**Naming Convention:**
- YYYY-MM-DD format (ISO 8601)
- Use date of when documents were moved to archive
- Example: 2026-01-14 (January 14, 2026)

### Version Folders (3.x.x/)

**What Goes Here:**
- Complete source code for that version
- All Python files
- Tests
- Configuration files
- __init__.py, manifest.json, etc.

**When to Create:**
- When starting development of a new version
- Copy from previous version as base
- Build incrementally in this folder

**Naming Convention:**
- Semantic versioning: MAJOR.MINOR.PATCH
- Example: 3.5.0, 3.5.1, 3.6.0

---

## 📋 ARCHIVING WORKFLOW

### When Updating a Document

**Example: Updating ROADMAP_v8.md → ROADMAP_v9.md**

1. **Before making changes:**
   ```bash
   cd "Context Snapshots"
   mkdir -p "Archive/2026-01-14"
   cp "Latest/ROADMAP_v8.md" "Archive/2026-01-14/"
   ```

2. **Make updates:**
   - Edit or create new version in Latest/
   - Save as ROADMAP_v9.md in Latest/

3. **Remove old version from Latest/:**
   ```bash
   # Delete the old version from Latest/ (already archived)
   rm "Latest/ROADMAP_v8.md"
   ```

4. **Update references:**
   - Update README.md if needed
   - Update CURRENT_STATE.md if relevant
   - Document changes in commit message

### When Completing a Version

**Example: After deploying v3.5.0 to production**

1. **Archive pre-deployment planning:**
   ```bash
   mkdir -p "Archive/2026-04-15"  # Deployment date
   cp "Latest/PLANNING_v3_5_0.md" "Archive/2026-04-15/"
   ```

2. **Update current state:**
   - Update CURRENT_STATE.md (production version now v3.5.0)
   - Update ROADMAP (mark v3.5.0 complete, adjust timeline)

3. **Optional: Keep planning doc in Latest/**
   - Useful for reference during bug fixes
   - Can remove later when no longer actively referenced

---

## 🔄 VERSION LIFECYCLE

### Planning Phase
```
Latest/
└── PLANNING_v3_5_0.md        (Created, actively referenced)
```

### Development Phase
```
Latest/
└── PLANNING_v3_5_0.md        (Referenced during development)

3.5.0/                         (Version folder created)
└── [source code being built]
```

### Deployment Phase
```
Latest/
└── PLANNING_v3_5_0.md        (Still current)

Archive/2026-04-15/
└── PLANNING_v3_5_0.md        (Copy made for history)

3.5.0/                         (Complete, deployed)
└── [production source code]
```

### Post-Deployment
```
Latest/
└── PLANNING_v3_6_0.md        (Next version planning)
   (v3.5.0 planning removed from Latest after stabilization)

Archive/2026-04-15/
└── PLANNING_v3_5_0.md        (Historical reference)
```

---

## 📦 ARCHIVE NAMING GUIDELINES

### Date Selection

**Use the date when:**
- Documents were superseded (preferred)
- Major version was deployed
- Architectural change occurred
- Planning pivot happened

**Example Dates:**
- `2026-01-14` - v3.5.0 planning created, v3.4/3.5 resequenced
- `2026-01-04` - v3.3.0 revision, multi-session strategy
- `2025-12-20` - v3.2.9 deployed
- `2025-11-15` - v3.0 dual-entry architecture

### What to Include in Each Archive

**Minimum:**
- Superseded document(s) that prompted the archive
- Date-stamped README explaining what changed

**Complete:**
- All documents from that snapshot
- Complete context package
- Summary of changes
- Rationale for updates

**Example Archive Contents:**
```
Archive/2026-01-14/
├── README.md                    (Explains this snapshot)
├── ROADMAP_v8.md               (Superseded by v9)
├── PLANNING_v3_3_0.md          (Original v3.3.0)
├── PLANNING_v3_3_0_REVISED.md  (Revised version)
└── MULTI_SESSION_STRATEGY.md   (Session 1-3 plan)
```

---

## 🎯 QUICK REFERENCE

### Finding Current Documents
**Location:** `Context Snapshots/Latest/`  
**Always current:** ROADMAP, VISION, PLANNING, QUALITY, CURRENT_STATE

### Finding Historical Documents
**Location:** `Context Snapshots/Archive/YYYY-MM-DD/`  
**Sort:** By date (most recent first)
**Purpose:** Historical reference, understanding evolution

### Finding Version Code
**Location:** `3.x.x/` folders at root level  
**Current production:** Check CURRENT_STATE.md  
**In development:** Check CURRENT_STATE.md

---

## 🛠️ MAINTENANCE TASKS

### Monthly
- [ ] Review Latest/ for outdated documents
- [ ] Archive any superseded versions
- [ ] Update CURRENT_STATE.md

### After Each Version Deployment
- [ ] Archive planning documents
- [ ] Update ROADMAP (mark complete)
- [ ] Update CURRENT_STATE.md
- [ ] Create deployment archive snapshot

### Quarterly
- [ ] Review all archives
- [ ] Consolidate if needed
- [ ] Update README.md
- [ ] Document major learnings

---

## ⚙️ AUTOMATION OPPORTUNITIES

### Git Tagging (Optional)
```bash
# After archiving a major snapshot
git add "Context Snapshots/Archive/2026-01-14/"
git commit -m "Archive: Pre-v3.5.0 planning snapshot"
git tag context-2026-01-14
```

### Backup Script (Optional)
```bash
#!/bin/bash
# backup-context.sh
DATE=$(date +%Y-%m-%d)
ARCHIVE_DIR="Context Snapshots/Archive/$DATE"
mkdir -p "$ARCHIVE_DIR"
cp -r "Context Snapshots/Latest/"* "$ARCHIVE_DIR/"
echo "Archived to $ARCHIVE_DIR"
```

---

## 📊 EXAMPLE TIMELINE

```
2025-11    v3.0 deployed
2025-12    v3.2.9 deployed     → Archive/2025-12-20
2026-01-04 v3.3.0 revised      → Archive/2026-01-04
2026-01-14 v3.5.0 planned      → Archive/2026-01-14
2026-04    v3.5.0 deployed     → Archive/2026-04-15 (future)
2026-07    v3.4.0 deployed     → Archive/2026-07-01 (future)
2026-10    v3.6.0 deployed     → Archive/2026-10-15 (future)
```

---

## ✅ CURRENT ACTIONS NEEDED

### Immediate (This Session)
1. ✅ Created ROADMAP_v9.md (in outputs)
2. ✅ Created CURRENT_STATE.md (in outputs)
3. ✅ Updated PLANNING_v3_5_0.md (in outputs)
4. ⏳ Create Archive/2026-01-14/ folder (manual)
5. ⏳ Move ROADMAP_v8.md to archive (manual)
6. ⏳ Move old v3.3.0 docs to archive (manual)
7. ⏳ Copy new documents to Latest/ (manual)

### Manual Steps for You
```bash
cd "Context Snapshots"

# 1. Create archive folder
mkdir -p "Archive/2026-01-14"

# 2. Archive superseded docs
mv "Latest/ROADMAP_v8.md" "Archive/2026-01-14/"
mv "Latest/PLANNING_v3_3_0.md" "Archive/2026-01-14/"
mv "Latest/PLANNING_v3_3_0_REVISED.md" "Archive/2026-01-14/"
mv "Latest/MULTI_SESSION_STRATEGY.md" "Archive/2026-01-14/"

# 3. Copy new docs from downloads to Latest/
cp ~/Downloads/ROADMAP_v9.md "Latest/"
cp ~/Downloads/PLANNING_v3_5_0.md "Latest/"
cp ~/Downloads/CURRENT_STATE.md "Latest/"

# 4. Verify
ls -la "Latest/"
ls -la "Archive/2026-01-14/"
```

---

**Folder Structure Guide**  
**Created:** January 14, 2026  
**Purpose:** Organize context with versioned history  
**Philosophy:** Active docs in Latest/, history in dated Archives/
