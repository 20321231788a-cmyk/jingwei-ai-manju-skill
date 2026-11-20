# 经纬AI，一键漫剧创作skill · V3.1

> **经纬AI，一键漫剧创作skill（V3.1 公开首发版 · 持续更新中）**：
> **1 总控入口（`SKILL.md`）+ 7 份核心规则库 + 4 套自动化 Python 脚本** · 四层纵深——**商业爽点提纯 / 画风锁与无损四视角资产 / 外化导演与三大模型高冲击编译 / 代码级反平淡机检与终审看板**。
>
> **画风锁（6 大内置主流画风 + 建剧未指定必提问自定义）** + **八条创作硬约束** + **四道代码级「平淡度一票否决」机检** · 产出可直接投喂 **Wan 3.0（30s）/ Seedance 2.0（15s）/ MiniMax H3（4–15s）** 的高密度提示词与可视化 HTML 制作看板（零第三方 Python 依赖，开箱即用）。

[![Version](https://img.shields.io/badge/Version-V3.1%20%E9%A6%96%E5%8F%91%E7%AC%AC%E4%B8%80%E7%89%88-f59e0b)](#)
[![Models](https://img.shields.io/badge/Models-Wan3.0%20%7C%20SD2.0%20%7C%20H3-b4a2ff)](#-三三套模型专属高冲击编译模具头部减脂--动作权重优先)
[![Python](https://img.shields.io/badge/Python-Stdlib%20Only%20(Zero%20Deps)-10b981)](#-六快速安装零依赖)
[![Status](https://img.shields.io/badge/Status-%E6%8C%81%E7%BB%AD%E6%9B%B4%E6%96%B0%E4%B8%AD-6366f1)](#-八持续更新说明与开源致谢)

---

## 💡 核心理念：用户只给原件，AI 跑完百条导演与机检规则

很多 AI 漫剧烧钱抽卡却依然“站桩念经、平淡无味”，根源在于：
1. **死守原件水词**：不敢砍废话、不把危机前置到前 3 秒，照抄小说导致划走率爆表；
2. **微表情陷阱**：低预算下让 AI 演“眼神微冷、手指轻攥”，抽卡 10 次也是面瘫站桩；
3. **切模型失真**：Wan3.0（30s）、SD2.0（15s）、H3（4–15s）提示词脾气完全不同，换模型转写直接丢掉动作和金句；
4. **画风写死或漂移**：新建项目套用固定画风，或跨镜头人脸与场景媒介分裂。

**「经纬AI，一键漫剧创作skill」（V3.1）通过「一层共用爽剧母本 + 前置画风锁 + 三套模型减脂编译器 + 代码级一票否决门禁」，把下限直接锁死在中上商业水准。**（内部技能目录名保留 `h3-storyboard-director` 以兼容既有项目引用）

---

## 🏗️ 架构总览：四层工业化生产链路

```text
原件剧本 / 小说章节
   │
   ▼  【第一层：前置锁与项目初始化】 (project-skills.md + style-presets.md)
   ├── 画风锁：未指定画风必向用户提问（6大内置主流画风 S1-S6 / 任意自定义）
   └── 独立入口：自动生成 <作品名>/AGENTS.md、专属 SKILL.md 与独立看板启动器
   │
   ▼  【第二层：爽点提纯与外化导演母本】 (directing.md + action-vfx.md)
   ├── 默认开启短剧脱水提纯：砍寒暄水词，前3秒痛点/异象暴击，三段式交锋+≤12字重锤金句
   ├── 强制爆点槽位：集级 thrill_plan（5要素+爽点强度1-10）+ 段级 dramatic_arc（三拍弧线）
   └── 外化动作红线：封杀微表情站桩，强制拍案震物、指鼻逼视、扣腕反压与大反差景别硬切
   │
   ▼  【第三层：高精资产与三模型高冲击编译】 (delivery.md + model-routing.md)
   ├── 资产锁定：分步生图 + stitch_character_sheet.py 无损拼接 3344×1882 四视角整图
   └── 一母本三模具：无损编译为 Wan3.0 (30s) / SD2.0 (15s) / H3 (4-15s) 头部减脂提示词
   │
   ▼  【第四层：代码级反平淡机检与看板交付】 (h3-prompt-practice.md + build_board.py)
   ├── 四道代码级「平淡度一票否决」机检 + 八条创作约束统一联审
   └── 导出深色紫灰《打开看板.html》终审包（授权后经适配队列提交生成）
```

---

## 🎨 一、自定义视觉画风锁（6 大内置主流画风 + 未指定必提问）

新建项目时，若用户未在指令或原件中明确画风，**Agent 将在建剧与生图前主动向用户提问确认**，不再把单一画风强行套给所有作品；确认后跨集锁定在项目专属技能与 `制作数据.json`（`style_name` + `style`）中：

| 代号 | `style_name` | 视觉特征与适用题材 |
| --- | --- | --- |
| **S1** | `r2混合媒介` | 唯美半写实 3D CG 人物 + 现实摄影级建筑实景，共用透视与有源光影（都市异能、现代民俗、末世悬疑） |
| **S2** | `2D厚涂韩漫` | 高清商业条漫/番剧厚涂赛璐璐，锐利线稿、强对比明暗与高饱和瞳孔发丝高光（都市逆袭、校园打脸、重生复仇） |
| **S3** | `3D国漫玄幻` | 全场景统一次世代 3D 国漫 CG，精细铠甲物理褶皱、体积光束与高密度法术粒子（修仙、高武、宗门大战） |
| **S4** | `新中式水墨` | 东方工笔水墨融合现代 CG，宣纸肌理底韵、工笔骨相、朱砂/青绿点染与写意墨气（武侠、权谋古风、志怪悬疑） |
| **S5** | `电影写实真人` | 电影胶片摄影质感，真实肤质伤痕、光学浅景深与高反差硬光塑形（刑侦悬疑、商战博弈、硬核末日） |
| **S6** | `暗黑赛博霓虹` | 高对比暗夜霓虹风，冷青/洋红双色逆光轮廓、雨夜湿石与玻璃镜面强反射（赛博科幻、都市异能夜战） |
| **自定义** | `custom` | 支持用户直接描述任意画风，或发 1–3 张风格参考图提炼渲染媒介、线条与光比后锁定 |

---

## 🔥 二、爽剧爆点引擎与低成本外化动作红线

1. **解除原件逐字死锁（默认商业短剧提纯）**：
   - 在守住核心主线、人设底色与最终胜负的前提下，自动删减客套寒暄、压缩铺垫，将危机或羞辱前置到 **前 3 秒**（若需一字不改原文，显式设置 `"strict_verbatim": true` 即可）。
   - 冲突对白强制按 **① 挑衅/逼迫 → ② 加码/亮底牌 → ③ 一锤定音反杀** 组织，每段提炼 **1 句 ≤12 字的短视频重锤金句**。
2. **必填爆点硬槽位**：
   - 集级 `thrill_plan`：`opening_hook_3s`（前3秒痛点钩）、`core_pain_point`（核心受压点）、`payoff_climax`（宣泄反杀爆点 + `thrill_level` 1–10）、`slice_highlight`（10–15秒切片名场面与重锤金句）、`ending_hook`（集尾断钩）。
   - 段级 `dramatic_arc`：`施压/蓄势拍 → 加码/极限拍 → 爆发反杀/悬念卡断拍`。
3. **低预算高出片率：外化大动作替代细腻微表情**：
   - ❌ 严禁作为主戏剧动作：`眼神微冷`、`嘴角微动`、`手指轻攥`、`原地站桩慢聊`、`无事匀速慢推`。
   - ✅ 强制外化为 AI 一次出片即可读的动作：`猛拍木桌震飞纸符`、`探身指鼻极近景逼视`、`闪电扣腕/拎领`、`一击震退/跌坐仰望`、`大反差景别硬切`、`冷暖光效骤变`。

---

## 🔄 三、三套模型专属高冲击编译模具（头部减脂 · 动作权重优先）

顶层爽剧母本与切片金句全模型共用，切换 `active_model` 时按以下**专属模具**无损编译：

| 模型分支 | 单条时长 & 引用 | 头部减脂硬限 | 单段台词上限 | 专属节奏与防平淡铁律 |
| --- | --- | --- | --- | --- |
| **Wan 3.0** (`wan3`) | **30 秒** · `图N` | **≤110 字**（推荐 ≤90 字） | **≤85 字** | 完整三拍闭环（`0–8s` 痛点起手 → `8–18s` 施压极限 → `18–30s` 反杀+金句+尾钩）；**第 15–20s 强制设一次景别大跳切+爆发动作**唤醒后半程动态。 |
| **Seedance 2.0** (`seedance2`) | **15 秒** · `@图片N` | **≤95 字**（推荐 ≤75 字） | **≤38 字** | 精准对拆为**前15s（蓄压断钩段：卡在反击起手一瞬）+ 后15s（宣泄反杀段：硬切出手+金句+死寂余波）**；2–3 镜动势接力，留足 5 秒纯动作呼吸区。 |
| **MiniMax H3** (`h3`) | **4–15 秒** / 双15s · `<Picture N>` | 材质 100% 关进前3字段 | 按毫秒切点估时 | `subject_definitions` / `summary` / `retention_analysis` 锁死画风与骨相；`detailed_description` **零静态材质套话、全用高爆发英文强动词**。 |

---

## 🛡️ 四、四道代码级「平淡度一票否决」机检（`scripts/build_board.py`）

不同于只靠文字提醒的纯 Prompt 技能，本技能内置 Python 标准库校验器，联审与导出时**自动执行代码级硬拦截**：

1. **跨模型爆点与金句丢失拦截**：自动提取 `thrill_plan.slice_highlight` 中的引号金句，核验其是否 100% 落在当前激活模型（Wan3 / SD2.0 / H3）的生效提示词中，切模型漏掉直接报错；
2. **提示词头部肥胖拦截**：自动计算第一镜时间戳之前的头部字数（Wan3 > 110 字、SD2.0 > 95 字直接拦截），防止冗长材质说明书吃光动作注意力；
3. **单段台词过载拦截**：校验 SD2.0（>38 字）与 Wan3（>85 字）台词密度，防止塞满长台词变成站桩念经；
4. **微表情站桩词拦截**：扫描动作描述，发现只有“眼神微、嘴角微、手指轻”等弱动作且无强外化动词时直接打回重写；并校验 `dramatic_arc` 三拍弧线与必填槽位。

---

## 📂 五、技能目录结构（1 入口 + 7 规则库 + 4 脚本）

```text
h3-storyboard-director/
├── SKILL.md                          # 总控入口：V3.1 八条创作约束、工作方式与制作边界
├── README.md                         # 本说明文档
├── agents/
│   └── openai.yaml                   # Agent 元数据与默认触发提示词
├── references/                       # 7 份核心规则库
│   ├── style-presets.md              # [新增] 6大内置主流画风预设库 + 未指定必提问画风锁
│   ├── directing.md                  # 爽点提纯引擎、thrill_plan/dramatic_arc、外化动作与三段式对话
│   ├── model-routing.md              # Wan3.0(30s) / SD2.0(15s) / H3(4-15s) 切分铁律与减脂编译模具
│   ├── h3-prompt-practice.md         # 提示词写法规范与「平淡度一票否决」八项对照审核
│   ├── action-vfx.md                 # 攻防因果推进与修仙/打戏特效美术分层
│   ├── delivery.md                   # 素材标准、同一数据源、一剧一看板与队列提交规范
│   └── project-skills.md             # 作品专属技能创建、画风锁继承与续作路由机制
├── assets/
│   ├── production-template.json      # 含 style_name / thrill_plan 的制作数据起步模板
│   ├── episode-board.html            # 深色紫灰终审看板样式模板
│   ├── character-reference-layout-r2.png  # 16:9 角色四视角设定图排版母版
│   └── laoli-MIT.txt                 # 历史工作台模板 MIT 许可保留文件
└── scripts/                          # 4 套零依赖 Python 标准库脚本
    ├── build_board.py                # 制作数据硬门禁机检 + HTML 终审看板导出器
    ├── create_project_skill.py       # 一键创建新作品专属技能（含 --style 画风锁）与独立看板启动器
    ├── stitch_character_sheet.py     # 四视角人设图无损拼接器（输出 3344×1882 / 3840×2160）
    └── test_build_board.py           # 13 项自动化单元测试套件
```

---

## 📦 六、快速安装（零依赖）

将本技能置于工作区的 `.agents/skills/h3-storyboard-director` 目录，即可被 **Antigravity / Codex / Claude Code** 等主流 Agent 自动挂载：

```powershell
# 方式一：使用 GitHub CLI 一键克隆到工作区
gh repo clone 20321231788a-cmyk/jingwei-ai-manju-skill .agents/skills/h3-storyboard-director

# 方式二：解压 V3.1 发行版压缩包
Expand-Archive -Path "经纬AI-一键漫剧创作skill-V3.1.zip" -DestinationPath .agents/skills/h3-storyboard-director -Force
```

运行离线自检（仅依赖 Python 标准库，无需 `pip install`）：

```powershell
python .agents/skills/h3-storyboard-director/scripts/test_build_board.py -v
# Expected: Ran 13 tests ... OK
```

---

## 🚀 七、三步全自动使用教程

1. **建剧并锁定画风（未指定画风时 Agent 会主动提问）**：
   - 将小说或剧本原件放入工作区，对 Agent 说：`使用 $h3-storyboard-director 帮我建新项目《作品名》并制作第1集`。
   - 若未指定画风，Agent 会展示 `S1–S6` 内置画风或自定义入口供你选择；也可以手动运行：
     ```powershell
     python .agents/skills/h3-storyboard-director/scripts/create_project_skill.py --project "作品名" --genre "题材" --style S2
     ```
2. **爽点提纯、人设拼图与多模型编译**：
   - Agent 自动提纯 `thrill_plan` 与 `dramatic_arc`，分步生成人物四视角图并用 `stitch_character_sheet.py` 无损拼接为 `3344×1882` 整图；
   - 默认按 `Wan3.0`（30秒）生成高冲击提示词，也可随时指定切换 `SD2.0`（15秒）或 `H3`（短补镜）。
3. **机检与看板终审**：
   ```powershell
   python .agents/skills/h3-storyboard-director/scripts/build_board.py <作品名>/<集数>/制作数据.json --final-review
   ```
   打开生成的 `打开看板.html`（或双击 `<作品名>/启动制作看板.cmd`）核对爽点骨架、三拍弧线与参考图，确认无误后一键复制提示词或通过适配队列提交生成。

---

## 🔄 八、持续更新说明与开源致谢

- **版本说明**：**V3.1** 为公开首发第一版，本技能将持续随视频模型能力（如 Seedance 2.5 等新模型接入、价格与平台适配、画质锁脸工作流优化）持续更新迭代。
- **方法借鉴与致谢**：部分戏剧工艺与冲突方法论借鉴了开源社区 [`short-drama-factory`](https://github.com/lixiaoxiao9888-create/short-drama-factory) 与 [`manju-laoli-skill`](https://github.com/lixiaoxiao9888-create/manju-laoli-skill) 的前置锁与质检思路，并结合本工作区“一层共用母本 + 多模型减脂编译器 + 一剧一看板”进行了独立重构。
