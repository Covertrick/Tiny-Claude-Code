---
name: code-review
description: 进行全面的代码审查，覆盖安全、性能与可维护性。在用户要求审代码、查 bug 或审计代码库时使用。
---

# 代码审查 Skill

你现在具备开展完整代码审查的能力。请按以下结构化流程进行：

## 审查清单

### 1. 安全（关键）

检查：
- [ ] **注入漏洞**：SQL、命令注入、XSS、模板注入
- [ ] **认证问题**：硬编码凭证、弱认证
- [ ] **授权缺陷**：缺少访问控制、IDOR
- [ ] **数据泄露**：日志或错误信息中的敏感数据
- [ ] **密码学**：弱算法、密钥管理不当
- [ ] **依赖**：已知漏洞（可用 `npm audit`、`pip-audit` 检查）

```bash
# 快速安全扫描
npm audit                    # Node.js
pip-audit                    # Python
cargo audit                  # Rust
grep -r "password\|secret\|api_key" --include="*.py" --include="*.js"
```

### 2. 正确性

检查：
- [ ] **逻辑错误**：差一错误、空值处理、边界情况
- [ ] **竞态条件**：无同步的并发访问
- [ ] **资源泄漏**：未关闭的文件、连接、内存
- [ ] **错误处理**：吞掉异常、缺少错误路径
- [ ] **类型安全**：隐式转换、滥用 any 类型

### 3. 性能

检查：
- [ ] **N+1 查询**：循环中的数据库调用
- [ ] **内存问题**：大块分配、引用滞留
- [ ] **阻塞操作**：异步代码中的同步 I/O
- [ ] **低效算法**：本可用 O(n) 却用了 O(n^2)
- [ ] **缺少缓存**：重复的昂贵计算

### 4. 可维护性

检查：
- [ ] **命名**：清晰、一致、有描述性
- [ ] **复杂度**：函数超过 50 行、嵌套超过 3 层
- [ ] **重复**：复制粘贴的代码块
- [ ] **死代码**：未使用的导入、不可达分支
- [ ] **注释**：过时、冗余，或该写却缺失

### 5. 测试

检查：
- [ ] **覆盖率**：关键路径已测试
- [ ] **边界情况**：null、空值、边界值
- [ ] **Mock**：外部依赖已隔离
- [ ] **断言**：有意义且具体

## 审查输出格式

```markdown
## Code Review: [file/component name]

### Summary
[1-2 sentence overview]

### Critical Issues
1. **[Issue]** (line X): [Description]
   - Impact: [What could go wrong]
   - Fix: [Suggested solution]

### Improvements
1. **[Suggestion]** (line X): [Description]

### Positive Notes
- [What was done well]

### Verdict
[ ] Ready to merge
[ ] Needs minor changes
[ ] Needs major revision
```

## 常见需标记的模式

### Python
```python
# 不好：SQL 注入
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
# 更好：
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# 不好：命令注入
os.system(f"ls {user_input}")
# 更好：
subprocess.run(["ls", user_input], check=True)

# 不好：可变默认参数
def append(item, lst=[]):  # 缺陷：共享的可变默认值
# 更好：
def append(item, lst=None):
    lst = lst or []
```

### JavaScript/TypeScript
```javascript
// 不好：原型污染
Object.assign(target, userInput)
// 更好：
Object.assign(target, sanitize(userInput))

// 不好：使用 eval
eval(userCode)
// 更好：不要对用户输入使用 eval

// 不好：回调地狱
getData(x => process(x, y => save(y, z => done(z))))
// 更好：
const data = await getData();
const processed = await process(data);
await save(processed);
```

## 审查常用命令

```bash
# 查看最近变更
git diff HEAD~5 --stat
git log --oneline -10

# 查找潜在问题
grep -rn "TODO\|FIXME\|HACK\|XXX" .
grep -rn "password\|secret\|token" . --include="*.py"

# 检查复杂度（Python）
pip install radon && radon cc . -a

# 检查依赖
npm outdated  # Node
pip list --outdated  # Python
```

## 审查工作流

1. **理解上下文**：阅读 PR 描述、关联 issue
2. **运行代码**：尽量本地构建、测试、运行
3. **自上而下阅读**：从主入口开始
4. **检查测试**：变更是否有测试？测试是否通过？
5. **安全扫描**：运行自动化工具
6. **人工审查**：对照上方清单
7. **撰写反馈**：具体、给出修复建议、语气友善
