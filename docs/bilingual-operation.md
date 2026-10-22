# 双语 Daily-Arxiv 配置、迁移和发布

本项目将共享原始论文与两种 AI 解读分开维护。首页与统计页面默认 English；EN / ZH只切换 AI 内容，标题、作者、原始摘要与 arXiv 链接不翻译。个人关键词和作者过滤只保存在当前浏览器，不控制仓库邮件。旧存储键不删除，旧站登录凭据不迁移。

## 配置

编辑 `pyproject.toml` 的 `[tool.daily_arxiv]`，提交并推送到 `main`（代码功能改动使用 PR）。只修改本地文件或只推送开发分支，生产配置不会改变。`categories` 是订阅分类；非空 Actions 变量 `CATEGORIES` 同时覆盖抓取、匹配和网页分类。研究者列表使用稳定 `id`、`display_name`、`enabled`、确认 `aliases`、未确认 `suspected_aliases`。停用时保留稳定 ID。当前名单以该配置为准；别名应有身份核验依据，不确定缩写保留为疑似，不触发邮件。不要仅凭缩写、姓氏或相似拼写确认身份。姓名匹配仅限订阅分类内已经抓到的论文，不能解决全部同名问题。

启用发布后的配置 push 会重新构建历史高亮。索引绑定配置和有效分类摘要；构建与数据刷新先后完成时，网页会暂时提示索引待更新，不展示旧配置标记。新增研究者/收件人不会追发历史。

| 修改内容 | 生效时间 | 范围 |
| --- | --- | --- |
| `categories` | push 后部署网页；下一次 Daily 按新分类抓取 | 使用 arXiv recent 窗口，旧数据保留 |
| `researchers` | push 后自动刷新已有论文的高亮 | 新发现按新名单冻结通知依据，历史不补发 |
| `notifications.recipients` | 下一次 Daily 冻结新发现时使用新名单 | 既有队列沿用原收件人 cohort，不追发历史 |
| SMTP 身份或授权码 | 公共参数 push；凭据另改 Actions Secrets | 收件人地址不能代替 SMTP 登录名 |

日常维护本地 `main` 即可，远端 `data` 专门保存生成结果，不需手动编辑或合入源码：

```bash
git switch main
git pull --ff-only
# Edit pyproject.toml.
git diff -- pyproject.toml
git add pyproject.toml
git commit -m "Update paper subscriptions"
git push
```

`main` 应跟踪新仓库的 `origin/main`。功能开发使用短期分支与 PR；批准自动清理的仓库可以在合并后删除开发分支。本地分支若有独有提交，先保留、审查，再决定是否删除。旧来源 remote 无需作为日常 push 目标。

`notifications.recipients` 配置稳定收件人 ID、邮箱与开关，当前名单以 `pyproject.toml` 为准；地址随公开配置保存，不打包进网页。`notifications.smtp` 使用 `smtp.qq.com:465`、`security="ssl"`，发件地址为 `yhjin1005@qq.com`。认证通过 `username_env`、`password_env` 指定的环境变量读取，默认 `SMTP_USERNAME`、`SMTP_PASSWORD`。QQ 邮箱使用客户端授权码，不要把授权码发到聊天、写入 TOML 或命令参数。

改用其他 SMTP 不需要改传输代码。按服务商要求选择 `ssl` 或 `starttls` 及对应端口，同时更新认证身份、发件地址和客户端密码。`timeout` 和 `max_attempts` 控制超时及明确失败重试次数。英文邮件同时包含纯文本和 HTML 版本；HTML 使用内联 Times New Roman 字体，客户端缺少该字体时回退到 Times 或系统衬线字体，不加载远程字体。一篇论文命中多位研究者只列一次。真实发送同时要求通知配置启用、显式 `--send`、`ALLOW_SMTP_SEND=1`、可用凭据和持久发布回调。

## 本地验证

使用 Bash/WSL、Git、uv、Python 3.12+、Node.js 22+ 和 actionlint 1.7.12。先单独准备工具，再执行 `uv sync --frozen`；Python 版本来自 `.python-version`。若 uv 本身安装在项目 `.venv` 内，切换解释器时可能被替换，建议将工具安装在独立环境。不要修改旧项目的环境。

```bash
uv sync --frozen
bash scripts/check.sh
uv run --frozen --no-sync python scripts/build_site.py --repository OWNER/REPO --output artifacts/site-review
```

`scripts/check.sh` 与 CI 共用，离线核验锁文件、Ruff、Python/Node 测试、脚本语法、活跃工作流及 diff 空白；Python 测试包含站点构建。它使用已准备的 `.venv`，不自动安装、同步或下载。工具不在 PATH 时，通过 `ARXIV_UV`、`ARXIV_NODE`、`ARXIV_ACTIONLINT` 指定可执行文件。actionlint 的可选 ShellCheck/Pyflakes 集成固定关闭，避免本地与 CI 检查范围不同。

测试使用模拟服务，不需要真实邮箱/模型凭据。网站预览与部署统一使用 `scripts/build_site.py`，认证密码通过环境变量 `ACCESS_PASSWORD` 提供，不改写源码中的认证配置。构建按显式静态文件清单复制资源，只注入仓库身份、语言、有效分类、匹配摘要和认证哈希，不复制邮件设置或生成数据。输出目录必须不存在。网站需要保留原有外部字体/图表资源的可访问性。

## 历史迁移

源项目保持只读；必要的最新远端快照取到目标项目的隔离目录。先保存源码/数据提交、源文件 hash 和原始分支信息。不要向本地中文源 `origin` push，不要再次 clone 覆盖目标目录。

```bash
python scripts/migrate_history.py --help
python scripts/migrate_history.py --chinese CN_SNAPSHOT --english EN_SNAPSHOT --output NEW_CANDIDATE
```

快照应包含 `data/`、`assets/file-list.txt` 和记录来源仓库/提交的 `SOURCE.json`。工具扫描实际数据树，不相信旧清单。每日期按去版本 arXiv ID 合并原始记录，保留中文顺序，追加英文独有 ID，完全相同重复可合并；元数据或同语言有效内容冲突则生成报告并停止，须由用户决定。

已有增强 JSONL 及有效行字节保持原样，Markdown 原文只改名为 `DATE_English.md` / `DATE_Chinese.md`。迁移清单记录来源、提交、各文件 hash、逐日数量、语言可用性、冲突、目标 hash。完整索引包含原始文件和两种语言文件。`pipeline-state.json` 中历史基线禁止自动补译；通知状态以该基线初始化，禁止历史补发。失败占位文本保留为历史事实，网页显示 AI 不可用，不会伪装成健康结果。

候选、清单和快照保存在忽略的 `artifacts/upgrade/`。迁移验收应独立检查全部源 AI/Markdown 字节、确定顺序的 raw 并集、目标 hash、索引与重复运行结果。候选验证报告不等于发布授权。

## 每日运行与恢复

`daily_update.py raw` 将验证后的原始新发现、冻结的研究者命中/收件人集合、索引和流水线状态放进同一候选清单，应用前统一检查 hash。原始数据可先发布；邮件不等待 AI。两次独立 `ai --language English|Chinese` 随后发布各自已接受结果。某语言中途失败仍保存该语言已完成论文与部分字段，另一语言继续运行。

`data/pipeline-state.json` 区分历史与新发现、每语言 pending/complete。`data/ai-checkpoints/LANGUAGE.json` 在数据分支持久保留恢复字段，不依赖短期 Actions artifact。复用绑定精确原始摘要/记录、语言、模型和 prompt；同日追加别的论文不会使同一原始记录失效。没有新论文时照常处理基线之后的缺译。历史已有健康解读不重生成。

`bash run.sh DATA_CHECKOUT NEW_OUTPUT` 只抓取并创建独立候选，原 checkout 不变；第三参数 `--generate` 才允许付费生成。该脚本从不真实发信或发布。工作流生成失败时会保存 artifact，但已提交的数据/另一语言不会回滚。

Daily 的定时配置为 `30 1 * * *`，即北京时间每天 09:30，实际启动时间由 GitHub 调度。启用开关或更新配置不会补触发已经过去的定时点；需要立即运行时，可显式在 Actions 手动运行 Daily arXiv，它会正常调用模型并按规则发信。原始数据位于远端 `data` 分支；网站直接读取该分支，不需要每次生成后重新部署网页。`ENABLE_DATA_WRITES=false` 会同时暂停 Daily 和维护入口的数据写入。

历史修复和指定日期 backfill 已退出日常 Actions 入口，保留 CLI 与[归档流程](workflow-archive/README.md)。恢复时显式选择语言，沿用 hash 检查、健康行保护和来源证据；下载旧 artifact 前还须核对原仓库和原工作流。模型/prompt/原始摘要/来源/语言不兼容的恢复请求在调用模型之前拒绝；缺少来源证明的旧 partial checkpoint 也拒绝。旧增强文件可以读取，旧完整 artifact 可审查；旧共享 `DATE.md` 目标不自动改写为另一语言，需重新生成明确语言的候选。不要直接编辑 manifest 绕过检查。

所有数据写入工作流共用 `arxiv-data` 并发组；配置刷新仅重建高亮，不产生历史邮件。发布器检查预期 GitHub origin、远端 data HEAD 和允许路径，不 force-push，不夹带源码。失败后保留候选和 checkout；多文件本地写入不是文件系统事务，检查中断状态再继续。

## 通知恢复与预览

持久通知键是稳定收件人 ID + 去版本论文 ID。同版本更新、cross-list、另一语言完成不重复通知。一次成功发送后，当日新入队论文留待下一次日期运行，以保持每收件人每日一封汇总。无新论文也会处理已有待发/明确失败队列；达到次数上限停止自动重试。

```bash
python scripts/notify.py --state DATA_CHECKOUT/data/notification-state.json --preview-dir NEW_PREVIEW
```

该命令只生成 `.txt` / `.html` / `.eml`。发送前先将 `sending` 状态提交并推送，成功后保存 `sent`。明确拒收记为 `failed`，可能已被 SMTP 接收或发送后状态无法落盘记为 `uncertain`；中断遗留 `sending` 也转为 `uncertain`。未知结果不自动重发，SMTP 无法保证严格 exactly-once。

人工核对邮箱/服务端记录和 Message-ID 后，用 `scripts/notify.py --state ... --resolve-recipient ID --resolve-paper ARXIV_ID --resolution sent|retry|cancelled --note '核验依据'` 记录整个汇总批次的决定，再通过正常数据发布流程提交。不要把凭据放进 note。禁用或地址改变的旧收件人批次不会静默转发至新地址。确需放弃时，可以带核验备注将 pending 批次显式 cancelled；不允许把未发送的 pending 直接标为 sent 或重置重试。通知失败在工作流最后明确报告，不回滚论文或阻断 AI 保存。

## 手动维护

常驻工作流为 Tests、Daily arXiv、Deploy website、Refresh researcher highlights 与 Maintenance。`Maintenance` 复用原 `release-check.yml` 路径以保留执行历史，只允许从 `main` 手动运行；不增加一次性日期专用工作流。

`browser` 验证已部署网站的密码入口与三种宽度，可填写当前展示日期中已完成双语的 `paper_id`，逐项核对实际 AI 内容。`smtp-auth` 只验证认证。`crawl` 只抓取一次并发布已验证原始新发现；`ai` 必须提供一个已有来源绑定、在历史基线之外的 `paper_id`，分别保存该论文的 English/Chinese 解读，不处理其他待补论文，也不重复调用已经完成的目标。没有真正新论文时等待下一批公告，不能把历史缺译改标为新论文测试。

维护入口与其他数据写入共用 `arxiv-data` 并发组；只读浏览检查也会等待此组，以免核验期间数据发生切换。写入阶段要求 `ENABLE_DATA_WRITES=true`；`ai` 还要求 `ENABLE_AI=true`，`recipient-mail` 还要求 `ENABLE_EMAIL=true`。浏览检查只接收网站密码，认证检查不检出数据、不启用发信。

最初发布用的 `mail` 阶段已退出 Actions 菜单，底层 `release_probe.py` 与原记录保留。固定探针 `initial-release-v1` 与 Message-ID 保存在 `notification-state.json.release_probes`；sent/cancelled 不重发，sending/uncertain 需要人工核验。明确失败也受次数上限约束。服务端接受不等于收件箱已确认送达。

用户明确要求验证新增收件箱或字体时，可手动运行 `recipient-mail` 阶段并提供启用的 `recipient_id`。对应 CLI 为 `release_probe.py --recipient-test ID --send --publish --source DATA_CHECKOUT --repository OWNER/REPO`，固定测试键为 `recipient-layout-v1:ID`；没有任意测试 ID 输入，也不改写原 `initial-release-v1`。每位收件人只执行一次此类测试，重复运行跳过 sent/cancelled，unknown 或中断状态要求人工证据。恢复时使用相同 `--recipient-test ID` 配合 `--resolve sent|retry|cancelled --note '核验依据' --publish`。测试邮件只验证字体和收件箱，不含历史论文，不改变普通通知的冻结收件人集合。

连接或认证失败时，先手动运行 `smtp-auth` 阶段。它调用 `release_probe.py --check-auth`，使用与正常发送相同的连接、TLS 和登录流程，仅诊断一次，不发送邮件、不读取或修改通知队列，也不消耗发送次数。输出仅包含脱敏的阶段、错误类别和数字 SMTP 状态码，不记录服务器原文或凭据；查明原因后再决定是否恢复相应发送。

更换发件地址后，已冻结的测试邮件会阻止直接重发。仅当探针状态为明确失败的 `failed` 时，才可通过 `release_probe.py --rebind-sender --note '公开核验依据' --source DATA_CHECKOUT --repository OWNER/REPO --publish` 把发件人迁移到当前配置；收件人测试还需相同的 `--recipient-test ID`。此操作不读取 SMTP 凭据、不发信，保留 `failed` 状态、原失败记录、次数、收件人和 Message-ID；`sending/uncertain/sent` 等状态禁止迁移。次数耗尽时仍需单独的人工带证据恢复，迁移不重置额度。之后仍须先确认新服务商的 Secrets 已替换，再诊断认证和执行邮件实测。

QQ 邮箱配置步骤：登录[网页版邮箱](https://mail.qq.com/)，在设置中开启包含 SMTP 的第三方客户端服务，按页面完成安全验证并生成授权码。在仓库 Actions Secrets 中将 `SMTP_USERNAME` 设置为 `yhjin1005@qq.com`，将 `SMTP_PASSWORD` 替换为该邮箱生成的客户端授权码；不要填写 QQ 登录密码或一次性验证码。参见 [QQ 邮箱授权码说明](https://service.mail.qq.com/detail/0/75)。授权码失效或被撤销后需生成新码并更新 Secret。不要在日志或本地浏览器测试文件中复制 Secrets。

## 发布与回退

本地成果完成不代表已发布。创建远端、push、部署、真实发信/调用付费模型和旧站修改须在用户授权的发布范围内执行。

1. 用户验收代码、测试、迁移报告、网页/邮件预览；所有源项目继续保留。
2. 用户授权后创建 `yuhanjin-ustc/daily-arxiv` 并推送源码及审核的数据分支。先核对目标名称归属/内容；目标存在冲突则停止。发布时确认 origin 指向该 GitHub 仓库；克隆时继承的本地源远端只能保留作来源，绝不能向它 push。
3. 配置 Secrets：`OPENAI_API_KEY`、`ACCESS_PASSWORD`、`SMTP_USERNAME`、`SMTP_PASSWORD`。配置 Pages 使用 GitHub Actions。缺少 ACCESS_PASSWORD 时，既有鉴权逻辑会开放阅读；为保持旧站密码访问行为，必须先配置该 Secret 再部署。
4. 经单独授权，实测邮件和少量真正新论文的双语生成。检查 durable queue、各语言恢复和费用，不用迁移历史作自动补发。优先手动运行，暂不同时打开两套定时任务。
5. 启用 `ENABLE_PAGES=true`、`ENABLE_DATA_WRITES=true` 后，手动 dispatch Deploy website 与 Refresh researcher highlights（变量变化本身不会重跑先前跳过的任务），核对仓库链接、GitHub Pages 子路径、鉴权、缺译、匹配版本及三种屏幕宽度。运行 Maintenance 的 `browser` 阶段时可填写已完成双语的新论文 `paper_id`，核对该篇实际显示的两种 AI 内容，避免仅检查缺译论文。按授权启用 `ENABLE_AI`、`ENABLE_EMAIL`。
6. 切换前再次只读核对两个旧仓库最新 data SHA，重新制作全量候选并验证迁移期间增量，保留旧候选和来源证据。若新仓库已经有 smoke test 产物，先冻结并保留该数据提交，将最新旧站数据作为有来源/hash 的增量审查合入；保留新仓库已付费的健康 AI、检查点、discovery 状态和通知队列，严禁用重新初始化的迁移候选整体替换。仅为从旧站新导入且尚未在新仓库发现的 ID 增加历史基线；遇到元数据/健康 AI 冲突需再次交由用户判断。当前迁移工具处理两个源快照，已有运行状态的第三方合并需要独立审查的增量方案，不是一键覆盖。完成基线核对后，短时停用旧定时任务，完成最终增量检查，再启用新站 `ENABLE_DAILY=true`；避免漏收论文或长期重复付费。
7. 经授权在旧站和旧 README 增加迁移入口；保留旧仓库、历史页面和可回退定时配置，不自动跳转或删除。

若新站/邮件/生成验证失败，在旧任务停用前保持旧站运行，新站 `ENABLE_DAILY/AI/EMAIL` 保持关闭。若切换后失败，先关闭新任务，保留队列/检查点/候选，再恢复旧任务到切换前记录的设置；恢复前核对最后处理的原始 IDs，避免两套任务同时运行。邮件 uncertain 批次单独核验，不用重跑整个流水线解决。新站已生成数据和旧站数据都保留，修复后重新核对增量、基线和源 hash 再切换。

分支清理遵循明确授权。检查每个真实远端分支的当前 head、关联 PR、合并祖先关系和独有提交数，保护 main/data、未合并工作及迁移证据。已批准自动清理的仓库可在 PR 合并后删除对应开发分支；其他删除仍需用户批准具体仓库/分支，本地候选表不构成删除授权。
