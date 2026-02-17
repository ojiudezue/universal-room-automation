# Git & GitHub Setup Instructions

**Location:** `/Users/ojiudezue/Code/universal-room-automation`

Run these commands in your terminal to complete the migration:

---

## Step 1: Initialize Git Repository

```bash
cd /Users/ojiudezue/Code/universal-room-automation

# Initialize Git
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: URA v3.3.5.3 migration

- Home Assistant custom integration
- 22 Python modules (~500KB code)
- Event-driven architecture
- Multi-person BLE tracking
- Zone aggregation system
- Music following coordination
- Pattern learning engine
- SQLite database integration

Documentation:
- Vision v7 (project philosophy)
- Roadmap v9 (development timeline)
- Quality standards and checklists
- Planning for v3.5.0 Camera Intelligence
- Planning for v3.4.0 AI Custom Automation
- Planning for v3.6.0 Domain Coordinators

Features:
- 74+ entities per room
- 2-5 second response time
- 178+ test coverage
- Multi-entry architecture (Integration → Zones → Rooms)

Status: Production-ready v3.3.5.3
"
```

---

## Step 2: Create GitHub Repository

You have GitHub CLI installed, so use this command:

```bash
# Create public repository
gh repo create ojiudezue/universal-room-automation \
  --public \
  --description "Advanced Home Assistant integration for person-aware room automation" \
  --source=. \
  --remote=origin \
  --push
```

**What this does:**
- Creates GitHub repository at `github.com/ojiudezue/universal-room-automation`
- Sets it as `origin` remote
- Pushes your initial commit
- Makes it public (can change to `--private` if preferred)

**Alternative (Manual):**
If gh CLI doesn't work, create via web:

1. Go to https://github.com/new
2. Repository name: `universal-room-automation`
3. Description: "Advanced Home Assistant integration for person-aware room automation"
4. Public/Private: Your choice
5. Click "Create repository"
6. Then run:
```bash
git remote add origin https://github.com/ojiudezue/universal-room-automation.git
git branch -M main
git push -u origin main
```

---

## Step 3: Tag the Initial Release

```bash
# Tag v3.3.5.3 as first Git version
git tag -a v3.3.5.3 -m "Production release v3.3.5.3

Migrated from OneDrive to Git version control.

Current features:
- Event-driven architecture (2-5s response)
- Multi-person BLE tracking
- Zone coordination
- Music following
- 74+ entities per room
- 178+ tests passing

First commit in new Git workflow.
"

# Push tags
git push --tags
```

---

## Step 4: Create Development Branch

```bash
# Create and switch to develop branch
git checkout -b develop

# Push develop branch
git push -u origin develop

# Switch back to main
git checkout main
```

**Branch Strategy:**
- `main` - Production-ready code (v3.3.5.3 currently)
- `develop` - Integration/testing branch
- `feature/*` - Feature branches (e.g., `feature/v3.5.0-camera-intelligence`)
- `hotfix/*` - Emergency production fixes

---

## Step 5: Set Up for Next Development Work

```bash
# Create feature branch for v3.5.0 (when ready to start)
git checkout -b feature/v3.5.0-camera-intelligence

# Or for bug fixes on v3.3.x
git checkout -b hotfix/v3.3.5.4-music-transitions
```

---

## Step 6: Verify Everything

```bash
# Check Git status
git status

# Check remotes
git remote -v

# Check branches
git branch -a

# View commit history
git log --oneline

# View tags
git tag
```

**Expected output:**
- Remote: `origin` pointing to GitHub
- Branches: `main`, `develop`
- Tags: `v3.3.5.3`
- Clean working directory

---

## Step 7: Set Claude Desktop Workspace (Optional)

If you get the workspace validation working:

1. In Claude Desktop, set `/Users/ojiudezue/Code/universal-room-automation` as workspace
2. This gives Antigravity full access to the project for future development

---

## Verification Checklist

After running the above commands:

- [ ] Git repository initialized
- [ ] Initial commit created with all files
- [ ] GitHub repository created
- [ ] Code pushed to GitHub
- [ ] v3.3.5.3 tag created and pushed
- [ ] `develop` branch created and pushed
- [ ] Can view repo at github.com/ojiudezue/universal-room-automation
- [ ] README displays correctly on GitHub
- [ ] All 22 Python files visible in `custom_components/universal_room_automation/`
- [ ] Documentation visible in `docs/` folder
- [ ] Quality files visible in `quality/` folder

---

## What's Next?

### Immediate Next Steps

1. **Review the migration** on GitHub
2. **Set up workspace** in Claude Desktop (if not already done)
3. **Choose your next task:**
   - Continue v3.3.x bug fixes
   - Start planning for v3.5.0
   - Review and update documentation

### Development Workflow (Going Forward)

When starting new work:

1. **Plan** - Use Opus, read docs/planning/
2. **Create feature branch** - `git checkout -b feature/my-feature`
3. **Develop** - Use Opus for complex code, Sonnet for tests
4. **Test** - Run pytest, use Sonnet for fixes
5. **Commit** - Regular commits as you work
6. **Push** - `git push -u origin feature/my-feature`
7. **Merge** - Merge to `develop` when ready, then to `main` when stable

### Key Resources

- **WORKFLOW_GUIDE.md** - Multi-model development strategy
- **docs/VISION_v7.md** - What we're building
- **docs/ROADMAP_v9.md** - Where we're going
- **quality/DEVELOPMENT_CHECKLIST.md** - How to build quality code

---

## Success! 🎉

Your URA project is now:
- ✅ Migrated from OneDrive
- ✅ In clean folder structure (no spaces)
- ✅ Under Git version control
- ✅ On GitHub for collaboration
- ✅ Ready for professional development workflow
- ✅ Integrated with Antigravity

You can now develop features using Git workflows and Antigravity's powerful tools!
