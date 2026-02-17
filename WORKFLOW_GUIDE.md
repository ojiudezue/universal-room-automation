# URA Development Workflow Guide

**Purpose:** Guide for using multiple AI models effectively in URA development with Antigravity/Claude Desktop

---

## 🎯 Model Selection Strategy

Since Claude Desktop requires **manual model switching** via the UI, choose your model based on the task type:

### 🔷 **Use Opus (or Gemini 2.0)** For:

**Planning & Architecture**
- Creating implementation plans for new features (v3.5.0, v3.6.0, etc.)
- Architectural design decisions
- Reviewing VISION/ROADMAP documents
- Complex refactoring across multiple files
- Database schema changes

**Complex Coding**
- New feature implementation (15+ hours effort)
- Multi-file changes with complex dependencies
- Coordinator logic (person tracking, zone aggregation)
- Event-driven architecture modifications
- Integration of new platforms (cameras, BLE, etc.)

**Why Opus?**
- Superior reasoning for architecture
- Better at maintaining context across large codebases
- More reliable for complex multi-step tasks

---

### 🔶 **Use Sonnet 3.5** For:

**Bug Fixing (Within Established Patterns)**
- Config flow validation fixes
- Sensor state updates
- Entity attribute corrections
- Known bug patterns (see `quality/QUALITY_CONTEXT.md`)
- Post-mortem implementations

**Code Reviews**
- Reviewing pull requests
- Checking adherence to quality standards
- Validation against development checklist

**Testing**
- Writing new test cases
- Fixing test failures
- Running test suite validation

**Documentation**
- Updating CURRENT_STATE.md
- Creating bug reports
- Writing post-mortems

**Why Sonnet?**
- Fast and efficient for well-defined tasks
- Excellent for pattern-based fixes
- Cost-effective for straightforward work

---

### ⚡ **Use Flash (if available)** For:

**Quick Tasks**
- Running commands
- File searches
- Quick edits to single files
- Formatting fixes
- Git operations

**Validation**
- Running tests
- Checking file structure
- Verifying deployments

---

## 📋 Recommended Workflow Patterns

### Pattern 1: New Feature Development

```
1. Switch to OPUS
   → Review docs/PLANNING_v3_X_0.md
   → Review docs/VISION_v7.md
   → Review quality/DEVELOPMENT_CHECKLIST.md
   
2. Stay in OPUS  
   → Implement feature
   → Create tests
   → Update documentation
   
3. Switch to SONNET
   → Run test suite
   → Fix any test failures
   → Validate against checklist
```

**Example:** Building v3.5.0 Camera Intelligence
- Opus for coordinator design and implementation
- Sonnet for test fixes and validation

---

### Pattern 2: Bug Fixing

```
1. Switch to SONNET (or use OPUS if complex)
   → Read quality/QUALITY_CONTEXT.md bug classes
   → Identify bug pattern
   → Check quality/POST_MORTEM_*.md for similar issues
   
2. Stay in SONNET
   → Implement fix
   → Write tests
   → Validate with checklist
   
3. Use SONNET or FLASH
   → Run tests
   → Deploy and verify
```

**Example:** Fixing music transition timing
- Sonnet for fix implementation (known pattern)
- Flash for running tests

---

### Pattern 3: Planning New Version

```
1. Switch to OPUS
   → Review current docs/CURRENT_STATE.md
   → Review docs/ROADMAP_v9.md
   → Brainstorm architecture
   
2. Stay in OPUS
   → Create docs/planning/PLANNING_v3_X_0.md
   → Design database schema
   → Plan coordinator changes
   → Estimate effort
   
3. Use OPUS or SONNET
   → Create task breakdown
   → Update ROADMAP if needed
```

**Example:** Planning v3.7.0
- Opus for all planning work
- Save Sonnet for implementation phase

---

## 🔄 How to Switch Models

**In Claude Desktop:**

1. Look for model selector (usually top of chat interface)
2. Click dropdown
3. Select desired model:
   - Claude 3.5 Opus
   - Claude 3.5 Sonnet  
   - Claude 3.5 Haiku/Flash (if available)
4. Continue conversation with new model

**Note:** Model context is maintained when switching, so you can change models mid-session.

---

## 💡 Best Practices

### 1. **Start Big, Finish Small**
- Begin complex tasks with Opus
- Switch to Sonnet for refinements and tests
- Use Flash for final validation

### 2. **Document Your Model Choice**
When starting a session, note which model you're using:
```
"Using Opus for v3.5.0 camera intelligence implementation"
```

### 3. **Leverage Context Documents**
Both Opus and Sonnet benefit from reading:
- `docs/VISION_v7.md` - What we're building
- `docs/ROADMAP_v9.md` - Where we're going
- `docs/CURRENT_STATE.md` - Where we are
- `quality/QUALITY_CONTEXT.md` - How we build

### 4. **Use Quality Checklist**
Reference `quality/DEVELOPMENT_CHECKLIST.md` regardless of model:
- Pre-development validation
- During development checks
- Post-development review

### 5. **Test Suite First**
Always run tests after changes:
```bash
pytest tests/ --cov=custom_components/universal_room_automation
```
Use Sonnet or Flash for test execution and simple fixes.

---

## 📊 Model Usage Matrix

| Task Type | Recommended Model | Why |
|-----------|------------------|-----|
| New feature planning | **Opus** | Complex reasoning needed |
| Feature implementation (15+ hrs) | **Opus** | Multi-file complexity |
| Bug fix (known pattern) | **Sonnet** | Fast, pattern-based |
| Bug fix (unknown root cause) | **Opus** | Deep debugging needed |
| Writing tests | **Sonnet** | Well-defined task |
| Running tests | **Sonnet/Flash** | Simple execution |
| Architecture changes | **Opus** | System-level thinking |
| Documentation updates | **Sonnet** | Straightforward writing |
| Code review | **Sonnet** | Pattern matching |
| Refactoring (single file) | **Sonnet** | Contained scope |
| Refactoring (multi-file) | **Opus** | Complex dependencies |
| Database schema design | **Opus** | Architectural decision |
| Config flow tweaks | **Sonnet** | Known patterns |

---

## 🎓 Learning From Experience

### What Works Well

✅ **Opus for Planning**
- v3.5.0 planning: Opus created comprehensive 62KB specification
- Caught architectural dependencies other models might miss

✅ **Sonnet for Known Bugs**
- Zone race condition fix: Fast implementation following documented pattern
- Config storage pattern: Quick fix using existing learnings

✅ **Model Switching During Work**
- Start feature with Opus (architecture)
- Switch to Sonnet for tests
- Back to Opus if unexpected complexity arises

### What to Avoid

❌ **Don't use Flash for complex planning**
- May miss subtle architectural issues

❌ **Don't overthink model choice**
- When in doubt, start with Opus
- Can always switch mid-task

❌ **Don't skip context documents**
- Models work better with full context
- 15 minutes reading saves hours of rework

---

## 🚀 Quick Reference

**Starting a new session? Ask yourself:**

1. **Is this exploring new architectural territory?** → Opus
2. **Is this fixing a known bug pattern?** → Sonnet
3. **Is this implementing a planned feature?** → Opus (start), Sonnet (tests)
4. **Is this running commands/tests?** → Flash or Sonnet
5. **Is this code review?** → Sonnet

**Rule of thumb:** When in doubt, use Opus. You can always switch to Sonnet for simpler subtasks.

---

## 📁 Integration with Antigravity

Since you're using **Claude Desktop + Antigravity**:

- ✅ All models have access to same tools (file editing, terminal, etc.)
- ✅ Context is preserved when switching models
- ✅ Task boundaries work across model switches
- ✅ Artifacts (task.md, plans) are shared across models

**Workflow:**
1. Set task boundary with `task.md`
2. Choose model based on task type
3. Switch models as needed during execution
4. Complete with validation (Sonnet/Flash)

---

**Remember:** The goal is efficiency and quality. Use the right model for the job, and don't hesitate to switch when the task changes!
