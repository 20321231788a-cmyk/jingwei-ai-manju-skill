"""Create a project-specific skill and routing entry without copying shared rules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re


def _ensure_board_launcher(folder, project):
    launcher = folder / '启动制作看板.cmd'
    if not launcher.resolve().is_relative_to(folder):
        raise ValueError('看板启动脚本不能链接到项目外。')
    if not launcher.exists():
        batch = (
            '@echo off\r\n'
            'chcp 65001 >nul\r\n'
            'cd /d "%~dp0.."\r\n'
            f'python tools\\studio\\launch.py --project "{project}"\r\n'
            'if errorlevel 1 pause\r\n'
        )
        launcher.write_bytes(batch.encode('utf-8'))
    return launcher


STYLE_PRESETS = {
    'S1': ('r2混合媒介', '3D半写实CG人物（柔缎瓷感肤质、精致国漫/BJD骨相）融入现实摄影级建筑实景，共用透视、尺度与有源光影。'),
    'r2混合媒介': ('r2混合媒介', '3D半写实CG人物（柔缎瓷感肤质、精致国漫/BJD骨相）融入现实摄影级建筑实景，共用透视、尺度与有源光影。'),
    'S2': ('2D厚涂韩漫', '高清商业条漫/番剧厚涂赛璐璐画风，干净锐利线稿、强对比明暗块面、高饱和瞳孔与发丝高光、戏剧化氛围光晕。'),
    '2D厚涂韩漫': ('2D厚涂韩漫', '高清商业条漫/番剧厚涂赛璐璐画风，干净锐利线稿、强对比明暗块面、高饱和瞳孔与发丝高光、戏剧化氛围光晕。'),
    'S3': ('3D国漫玄幻', '次世代全3D国漫玄幻CG质感，角色与宏大仙侠场景统一3D高精度渲染，盔甲衣袂物理褶皱、体积光束与高密度粒子特效。'),
    '3D国漫玄幻': ('3D国漫玄幻', '次世代全3D国漫玄幻CG质感，角色与宏大仙侠场景统一3D高精度渲染，盔甲衣袂物理褶皱、体积光束与高密度粒子特效。'),
    'S4': ('新中式水墨', '新中式工笔水墨与现代CG融合，宣纸淡雅肌理、工笔勾线骨相、青绿与朱砂高饱和局部点染、写意墨气拖尾。'),
    '新中式水墨': ('新中式水墨', '新中式工笔水墨与现代CG融合，宣纸淡雅肌理、工笔勾线骨相、青绿与朱砂高饱和局部点染、写意墨气拖尾。'),
    'S5': ('电影写实真人', '写实电影胶片摄影质感，真实皮肤纹理与汗渍伤痕、实拍光学浅景深、高反差硬光塑形与轻微胶片颗粒。'),
    '电影写实真人': ('电影写实真人', '写实电影胶片摄影质感，真实皮肤纹理与汗渍伤痕、实拍光学浅景深、高反差硬光塑形与轻微胶片颗粒。'),
    'S6': ('暗黑赛博霓虹', '暗黑赛博朋克霓虹都市画风，冷青与洋红双色逆光轮廓、雨夜湿石与玻璃镜面强反射、硬朗金属科技材质。'),
    '暗黑赛博霓虹': ('暗黑赛博霓虹', '暗黑赛博朋克霓虹都市画风，冷青与洋红双色逆光轮廓、雨夜湿石与玻璃镜面强反射、硬朗金属科技材质。'),
}


def resolve_style(style, style_name=''):
    raw = style.strip()
    name = style_name.strip()
    if not raw and not name:
        return (
            '画风尚未指定（建剧必问用户确认）：请先向用户提问选择内置主流画风'
            '（S1 r2混合媒介 / S2 2D厚涂韩漫 / S3 3D国漫玄幻 / S4 新中式水墨 / S5 电影写实真人 / S6 暗黑赛博霓虹）'
            '，或由用户自定义画风描述/参考图后再开始生图与写提示词。'
        )
    if raw in STYLE_PRESETS:
        preset_name, preset_desc = STYLE_PRESETS[raw]
        return f'**已锁定画风 `{name or preset_name}`**：{preset_desc}'
    return f'**已锁定画风 `{name or "自定义画风"}`**：{raw or name}'


def create(root, project, genre='', director='', style='', style_name=''):
    root = Path(root).resolve()
    if (not project.strip() or project != project.strip() or project.endswith('.')
            or any(c in project for c in '<>:"/\\|?*\r\n') or any(ord(c)<32 for c in project)
            or project.startswith('.') or project.casefold() in ('tools', '制作资料')
            or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', project, re.I)):
        raise ValueError('作品名须为单层有效文件夹名称，不能使用工具目录名或路径。')
    folder = (root/project).resolve()
    if folder.parent != root:
        raise ValueError('项目须位于本工作区内。')
    master = root/'.agents/skills/h3-storyboard-director/SKILL.md'
    if not master.is_file():
        raise ValueError('工作区缺少主技能。')
    name = 'story-' + hashlib.sha256(project.encode('utf-8')).hexdigest()[:12]
    skill = folder/'.agents/skills'/name/'SKILL.md'
    entry = folder/'AGENTS.md'
    if not skill.resolve().is_relative_to(folder) or not entry.resolve().is_relative_to(folder):
        raise ValueError('项目入口不能链接到项目外。')
    route = f'.agents/skills/{name}/SKILL.md'
    if entry.exists() or skill.exists():
        if entry.is_file() and skill.is_file() and route in entry.read_text(encoding='utf-8-sig'):
            _ensure_board_launcher(folder, project)
            return skill, False
        raise ValueError('已有项目入口或专属技能；请读取后合并，不自动覆盖。')
    master_link = Path(os.path.relpath(master, skill.parent)).as_posix()
    description = f'仅用于《{project}》的视觉画风锁、题材、导演拍法与跨集一致性；创作和续作时配合工作区主技能读取。'
    style_block = resolve_style(style, style_name)
    content = f'''---
name: {name}
description: {json.dumps(description, ensure_ascii=False)}
---

# 《{project}》专属创作技能

仅适用于本作品目录。先读[公共制作技能]({master_link})，再按本文件细化创作。这里只保存本剧差异；完整稿、提示词、素材和执行状态仍在现有制作数据中维护。

## 视觉画风锁

{style_block}

## 题材与情绪目标

{genre.strip() or '题材尚未确定；读完原件后填写本剧的题材、核心冲突和情绪目标，不凭空补剧情。'}

## 导演拍法

{director.strip() or '尚未选定主摄影倾向；依据原件匹配后，写清构图、调度、运镜、剪辑和声音如何服务本剧情绪。'}

以上初始方向由创建者录入，不自动代表用户确认。创作时依据已有对话与原件标明用户指定、原件事实或Agent设计；各集director_style保留本集实际采用的方法。

## 连续性依据与改编边界

首次读完原件后，在此引用真实原件与现有设定路径，补入本剧跨集有效的选择及已授权改编范围；未提供内容不编造成已确认事实。后续只更新长期变化，不抄逐镜正文或记录工作流水账。用户最新修订优先，不因风格调整改写历史提交快照。
'''
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(content, encoding='utf-8')
    entry.write_text(f'# {project}\n\n处理本作品时先读[项目专属技能]({route})及其引用的工作区主技能，再读本次原件、最新修订和当前集制作数据。不加载其他作品的设定，不复制公共制作流程。\n', encoding='utf-8')
    _ensure_board_launcher(folder, project)
    return skill, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--genre', default='')
    parser.add_argument('--director', default='')
    parser.add_argument('--style', default='', help='内置画风代号(S1-S6)或自定义画风描述')
    parser.add_argument('--style-name', default='', help='简短画风标签名(写入看板style_name)')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[4])
    args = parser.parse_args()
    try:
        path, created = create(args.root, args.project, args.genre, args.director, args.style, args.style_name)
        print(('已创建：' if created else '已存在，保留原内容：') + str(path))
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
