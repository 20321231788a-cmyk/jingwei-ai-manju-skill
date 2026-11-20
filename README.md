# 漫剧分镜导演 `h3-storyboard-director` · V3.1

**高爽感、强切片爆点、低成本一次出片的商业 AI 漫剧全流程导演与多模型（Wan3.0 / SD2.0 / H3）分镜生成技能。**

---

## ✨ V3.1 核心升级亮点

1. **默认商业短剧爽点提纯（破除原件逐字死锁）**
   - 在守住原件核心主线、人设底色与最终胜负的前提下，自动砍掉寒暄与解释水词，将危机/羞辱/异象前置到开场前 3 秒，把平淡对话提纯为**「挑衅 → 加压 → 反杀」三段式交锋**，并提炼 **≤12 字短视频重锤金句**。
2. **强制爽剧爆点骨架（`thrill_plan` + `dramatic_arc` 必填硬槽位）**
   - 集级必填 `thrill_plan`（`opening_hook_3s` 前3秒痛点钩、`core_pain_point` 核心受压点、`payoff_climax` 宣泄反杀爆点、`thrill_level` 爽点强度 1–10、`slice_highlight` 切片名场面与重锤金句、`ending_hook` 集尾断钩）。
   - 段级必填 `dramatic_arc`（`施压/蓄势拍 → 加码/极限拍 → 爆发反杀/悬念卡断拍`），终结单段情绪平推。
3. **低成本高出片率：外化大动作替代细腻微表情**
   - 严禁以“眼神微冷、嘴角微动、手指轻攥、原地慢聊、无事慢推”充当主戏剧动作；强制外化为 AI 一次生成就能看清的**拍案震物、指鼻逼视、扣腕拎领、一击震退、高低位压迫构图与大反差景别硬切**。
4. **一层共用爽剧母本 + 三套模型专属高冲击编译模具**
   - **Wan 3.0（30秒/条，`图N`）**：头部画风与图序绑定硬限 `≤110字`（推荐 `≤90字`），单段台词 `≤85字`，包含 `0–8s痛点起手 → 8–18s施压极限 → 18–30s骤切反杀+金句+尾钩`，并在第 `15–20秒` 强制设置一次**大反差景别跳切 + 爆发动作**唤醒后半段动态。
   - **Seedance 2.0 / SD2.0（15秒/条，`@图片N`）**：头部硬限 `≤95字`（推荐 `≤75字`），单段台词 `≤38字`，将 30 秒闭环精准对拆为**前 15 秒（蓄压断钩段：卡在反击起手瞬间）**与**后 15 秒（宣泄反杀段：硬切出手 + 金句落锤 + 死寂余波）**，单条 2–3 镜动势接力。
   - **H3（4–15秒 / 双15秒包，`<Picture N>`）**：身份几何与 BJD 材质 100% 锁死在前三个字段（`subject_definitions` / `summary` / `retention_analysis`），`detailed_description` **零材质套话、全用高爆发英文强动词**与精确毫秒切点。
5. **代码级「平淡度一票否决」硬门禁（`scripts/build_board.py`）**
   - 自动校验跨模型切换时切片金句是否 100% 落地、提示词头部是否超字数、单段台词是否过载、是否存在微表情站桩描述，并一键导出深色可视化终审看板 `打开看板.html`。

---

## 📦 安装方法

将本技能放置于工作区的 `.agents/skills/h3-storyboard-director` 目录即可被 Antigravity / Codex / Claude Code 自动识别：

```powershell
# 方式一：使用 GitHub CLI 一键克隆
gh repo clone 20321231788a-cmyk/h3-storyboard-director .agents/skills/h3-storyboard-director

# 方式二：解压 V3.1 压缩包至工作区技能目录
Expand-Archive -Path h3-storyboard-director-V3.1.zip -DestinationPath .agents/skills/h3-storyboard-director -Force
```

运行离线自检（仅使用 Python 标准库，零外部依赖）：

```powershell
python .agents/skills/h3-storyboard-director/scripts/test_build_board.py -v
```

---

## 🚀 快速使用教程

1. **创建作品专属入口与独立看板**：
   ```powershell
   python .agents/skills/h3-storyboard-director/scripts/create_project_skill.py --project "作品名" --genre "题材"
   ```
2. **一键提纯分镜与多模型提示词**：
   在对话中发送原件并指定模型（默认 `Wan3.0` 30秒，或指定 `SD2.0` 15秒 / `H3` 补镜），Agent 将自动提纯 `thrill_plan` 爽点骨架、四视角人设拼图与模型正文，并写入 `<作品名>/<集数>/制作数据.json`。
3. **硬门禁校验与导出终审看板**：
   ```powershell
   python .agents/skills/h3-storyboard-director/scripts/build_board.py <制作数据.json> --final-review
   ```
   打开生成的 `打开看板.html` 或双击 `<作品名>/启动制作看板.cmd` 进行终审与复制/提交。
