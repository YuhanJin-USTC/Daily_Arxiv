# 两个仓库统一升级与补录：按顺序操作

这套教程适用于英文 `YuhanJin-USTC/daily-arXiv-ai-enhanced` 和中文 `YuhanJin-USTC/daily-arXiv-ai-enhanced-chinese`。两个压缩包是同一版实现，不要叠加之前的 `fix.patch`、`deepseek-update.patch` 或中文旧补丁。新版迁移工具会检查文件哈希，替换已知旧版本并移除被取代的旧脚本/报告；遇到未知修改会停止，避免覆盖你的工作。

**代码和离线验证已完成；线上尚未更新，真实 AI 摘要尚未补录。** GitHub 写入此前返回 403，开发环境也没有模型凭据。认证错误必须通过有效的 DeepSeek key 解决，代码不能把无效 key 变成有效 key。

## 1. 暂停旧任务，准备两个独立代码工作区

先在两个仓库各打开 **Actions → 原日常工作流 → 右上角菜单 → Disable workflow**，避免修复期间旧任务继续发布错误数据。不要删除仓库或 `data` 分支。

本地需要 Git、Python 3.12、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Node.js 22+。Windows 建议使用 Git Bash；下列终端命令采用 Bash。若已有修改，请先保存/提交，或新建干净克隆。不要执行 `git reset --hard`、`git clean -fd` 来绕过检查。

```bash
git clone https://github.com/YuhanJin-USTC/daily-arXiv-ai-enhanced.git daily-arxiv-english
git clone https://github.com/YuhanJin-USTC/daily-arXiv-ai-enhanced-chinese.git daily-arxiv-chinese
```

将对应压缩包解压到代码目录之外，例如 `daily-arxiv-unified-english/` 和 `daily-arxiv-unified-chinese/`，两者与上面的代码目录并列。**不要把整个压缩包上传进仓库，也不要把 `files/` 当成仓库根目录上传。**

## 2. 在两个仓库分别应用、测试并提交代码 PR

英文仓库：

```bash
cd daily-arxiv-english
git switch -c fix/unified-arxiv
python ../daily-arxiv-unified-english/apply_update.py --repo . --check
python ../daily-arxiv-unified-english/apply_update.py --repo . --apply
uv sync --frozen
uv run --frozen ruff check ai daily_arxiv scripts to_md tests
uv run --frozen ruff format --check ai daily_arxiv scripts to_md tests
uv run --frozen python -m unittest discover -s tests -v
node --test tests/test_frontend.cjs
git diff --check
git diff --stat
```

检查 `pyproject.toml` 中 `language = "English"`，并确认改动没有生产 `data/` 文件。然后：

```bash
git add -A
git commit -m "fix: unify arXiv coverage, AI recovery and safe publication"
git push -u origin fix/unified-arxiv
```

在 GitHub 点 **Compare & pull request**，目标选择 **main**。等 Tests 通过后审阅合并。

中文仓库使用同样命令，但进入 `daily-arxiv-chinese`，迁移工具路径改成 `../daily-arxiv-unified-chinese/apply_update.py`，核对 `language = "Chinese"`。两个仓库的核心代码、测试、工作流完全一致，唯一有意保留的源码差异是这个语言值。

如果检查报“未知文件版本”或“工作区不干净”，先保存本地改动并查看提示文件。不要用覆盖复制绕过检查。包中的 `fix.patch` 是给审阅和干净原始基线使用的备选；已经运行迁移工具后不要再应用它。

## 3. 一次性配置 GitHub

分别在两个仓库设置：

1. **Settings → Secrets and variables → Actions → Secrets → OPENAI_API_KEY**：确认它是官方 DeepSeek 账户当前有效的 key。英文 401 需要在这里修正。只在 GitHub secret 编辑框中输入，不要粘贴到聊天、代码、命令或日志。中文原 key 若有效不必更换。不要拿 `TOKEN_GITHUB` 或 `GITHUB_TOKEN` 当模型 key。
2. 模型、端点、思考强度与语言已写入 `pyproject.toml`，不需要设置 `MODEL_NAME`、`OPENAI_BASE_URL`、`LANGUAGE` 变量。旧值不再被新流程读取。
3. `CATEGORIES` 为空时使用默认六个物理分类；如旧变量不是这六类且你希望保持本次审计范围，清空它。不要扩成全 arXiv 后仍拿 91 篇作为验收数量。
4. **Settings → Actions → General → Workflow permissions**：允许工作流按声明写入仓库内容，供日常任务推送 `data`。历史恢复与补抓工作流仍只有读取权限，不会自动推送或合并。
5. **Settings → Pages → Build and deployment → Source → GitHub Actions**。这是新版网站发布方式，必须切换，不能继续直接发布含配置占位符的源码分支。
6. 运行 **Actions → Deploy website → Run workflow → main**。它按仓库身份和语言生成网站配置；原有 `ACCESS_PASSWORD` 如存在会继续使用。确认网站从正确仓库读取数据，历史失败摘要显示“AI summary unavailable”并回退到原始 abstract。

最高能力配置为 `deepseek-flash`（核对日期 2026-10-21，对应 V4.1-Flash-1017）、思考开启、`max`、输出上限 393216、原生 1M 上下文。输出上限不是必须生成的长度；当前输入仍是 abstract，没有假装读取论文全文。不会通过降低模型或思考强度掩盖参数错误。

## 4. 先修已有 AI 字段，再补漏抓论文

两个仓库都使用 **Stage historical AI repairs**，先 `generate=false` 审计，确认数量后再 `generate=true`。

| 仓库 / 阶段 | start | end | ids | expected_count | 预期失败数 |
| --- | --- | --- | --- | --- | ---: |
| 中文单篇 | 2026-10-20 | 2026-10-20 | 2610.26164 | 59 | 1 |
| 英文首次审计 | 2026-10-15 | 2026-10-20 | 留空 | 留空 | 226 |
| 英文小批试跑 | 2026-10-17 | 2026-10-17 | 留空 | 6 | 6 |

中文必须先运行单篇修复：工具要求 59 条、其余 58 条完整，只填目标缺失字段，另外 58 行逐字节不变。输出包括一个候选 JSONL 和由它生成的当天 Markdown；原始 raw JSONL 不变。

英文先用 10 月 17 日的 6 篇验证实际认证与英文摘要质量。成功并按下一节合并后，再逐日恢复 15、16、18、19、20 日，失败数分别为 **35、39、39、48、59**。也可以重新审计 15–20 日，此时已修复的 6 篇应被跳过，剩余 220 篇。最大思考模式下建议逐日运行，避免六小时工作流超时。

成功时下载运行底部的 `arxiv-recovery-...` artifact，解压后找到 `ready/manifest.json`、`ready/data/`。确认 manifest 的 `complete` 为 `true`。**有 artifact 不等于成功**：失败运行也会保留审计与 checkpoint；`complete=false` 或没有完整 manifest 的目录不能发布。

若 401/403，任务应立即失败，不会继续跑完整天，也不会发布占位字段。修正 key 后开一次新运行；不要点旧故障运行的 Re-run，因为它可能使用旧代码。若结构仍不完整，保留 checkpoint；命令行可用 `python -m ai.recover ... --generate --output 新目录 --resume 旧目录/checkpoints` 继续，源文件和语言必须一致。

## 5. 把候选数据放入独立 data PR

下面以英文某一天的成功 artifact 为例。先确保本地代码已更新到合并后的版本，并在代码仓库根目录运行。将 `/absolute/path/artifact/ready` 改成实际解压路径；分支名和 worktree 名称每批使用新的名字。

```bash
git fetch origin main data
git switch main
git pull --ff-only origin main
uv sync --frozen
git worktree add -b repair/ai-20261017 ../daily-arxiv-english-data origin/data

uv run --frozen python scripts/apply_staged.py \
  --source ../daily-arxiv-english-data \
  --staged /absolute/path/artifact/ready --verify-only

uv run --frozen python scripts/apply_staged.py \
  --source ../daily-arxiv-english-data \
  --staged /absolute/path/artifact/ready

git -C ../daily-arxiv-english-data diff --stat
git -C ../daily-arxiv-english-data diff --check
```

核对该日仅有增强 JSONL 和 Markdown 两个文件变化、五个 AI 字段完整、语言正确、内容符合摘要。中文同理，worktree 改成 `daily-arxiv-chinese-data`，分支用 `repair/ai-2610-26164`；确认 JSONL 只改变 `2610.26164` 一条记录。

```bash
git -C ../daily-arxiv-english-data add -- data
git -C ../daily-arxiv-english-data commit -m "data: repair reviewed archived AI summaries"
git -C ../daily-arxiv-english-data push -u origin HEAD
```

在 GitHub 创建 PR，**base 选 data，不是 main**。在 PR 描述写入修复日期、ID、manifest 中的源/候选 SHA-256。审阅后合并。不要把 artifact 的旧文件整包覆盖到当前 data 分支；如果哈希校验失败，说明归档已变化，需要重新审计/生成，不能强制覆盖。

已提交、推送并合并的 worktree 可用 `git worktree remove ../daily-arxiv-english-data` 清理；下批从最新 `origin/data` 新建分支与 worktree。保留源 commit 和 manifest 供回滚，回滚使用 `git revert` 修复提交，不重置整个 data 分支。

## 6. 再补 10 月 20 日漏抓的论文

先确认该仓库 10 月 20 日已有 59 条记录的 AI 都已修好并合并。然后：

1. 在该仓库运行 **Stage missing 2026-10-20 papers**，`generate=false`。它使用已核对的 91-ID 公告清单，只请求尚未发布的 ID，不调用模型。查看 `coverage.json`，原始状态应是 59 个已发布、32 个待补。
2. 若某些缺失 ID 已被其他新运行补入别的日期，待补数量会相应减少。这是全库按 ID 去重的结果，不能强制重新生成来凑 32。
3. 运行相同工作流，`generate=true`。只为这些新论文生成 AI，候选增强文件在原有字节后追加，旧记录不会重算或改写。未先修好的历史占位数据会在付费生成前触发拒绝。
4. 下载 `arxiv-backfill-...` artifact。按第 5 节的同一验证/应用方式创建独立 data PR。本次应涉及当天 raw JSONL、增强 JSONL、Markdown 和 `assets/file-list.txt`，不是旧 AI 修复的两文件范围。
5. 在最初 59 篇且没有其他提前补抓的情况下，增强数据变为 **91 篇**；原 raw 文件有 64 行 / 59 个唯一 ID，旧重复行被保留，所以追加后 raw 行数不能当成论文总数。网页 All 统计应按唯一 ID 计数。

中英文各执行一次。这个清单保留在源码中，超过官网最近五个公告日窗口后仍可补抓，不需要重新生成当天已有论文。

补抓或日常批次中途失败时，artifact 会保留原始 raw 文件和 `ready/checkpoint.json`。可在已配置凭据的可信本地环境用 `python scripts/stage_daily.py --source 数据工作区 --raw 原始raw文件 --date 原日期 --output 新目录 --resume 旧ready/checkpoint.json` 继续；源 raw 哈希和语言必须一致，已完成的字段会复用。重新下载一批不同内容的 raw 后不能套用旧 checkpoint。

## 7. 恢复自动更新并验收

两个仓库分别启用 **Daily arXiv**，从 `main` 发起新运行。验收：

- 无新论文时正常结束，不改历史文件；有新论文时 coverage 与最终 ID 集合一致。
- AI、质量校验和发布全部成功；任何模型/内容检查/抓取错误都应阻止数据推送。
- 日常任务只提交 `data`，不把缓存、临时 JSON、模型响应或生成的网站配置提交到 `main`。
- 网页显示正确语言；失败历史数据有明确原始摘要回退；交叉分类可筛出论文；All 数量去重。
- 同一天再次运行只处理新 ID；旧增强记录字节不变。若 data 在任务期间更新，推送停止，不会自动 rebase 覆盖新数据。

上传的英文旧报告还提到更早的大量失败记录。修好机制和这六天并不等于那些历史摘要自动恢复。用以下命令只读盘点整个归档：

```bash
uv run --frozen python -m ai.quality ../daily-arxiv-english-data/data --audit-history
```

对报告中有有效 raw abstract 的日期继续使用同一个恢复工作流，按日修复、审阅、合并；正常日期自动跳过。空文件、缺失 raw、摘要不一致的日期会停止，必须先核对原始论文清单。不要将较早故障都归因于 401，也不要为不存在的原始摘要编造五字段。

## 8. 保持两个项目长期一致

今后共享代码修复同时移植到两边，并运行相同 CI。不要再分别维护两套 `enhance.py` 或模型适配器。保留两份 `pyproject.toml` 的语言差异，其余共享文件应一致；仓库身份由网站构建自动注入。

`.venv`、`__pycache__`、`.ruff_cache`、`.env`、`_site` 和运行 artifacts 已纳入忽略规则。临时写入文件会自动清理。工作流 artifacts 保留 14 天，失败 checkpoint 是可恢复证据，确认不再需要后再删除；不要把它们复制到源码仓库。
