//! 多 agent 的会话恢复参数（与 ccs 的 Python 适配层保持同一张表）。
//!
//! 这里的模板用于生成 Herdr 的 pane report-agent-session 的 RESUME_COMMAND，
//! 以及 restore 时提示的恢复方式。

use crate::json::Json;
use crate::paths;

pub struct Agent {
    pub kind: &'static str,
    pub aliases: &'static [&'static str],
    pub resume: Option<&'static [&'static str]>,
    pub cont: Option<&'static [&'static str]>,
}

pub static AGENTS: &[Agent] = &[
    Agent {
        kind: "claude",
        aliases: &["claude"],
        resume: Some(&["{exe}", "--resume", "{sid}"]),
        cont: Some(&["{exe}", "--continue"]),
    },
    Agent {
        kind: "codex",
        aliases: &["codex"],
        resume: Some(&["{exe}", "resume", "{sid}"]),
        cont: Some(&["{exe}", "resume", "--last"]),
    },
    Agent {
        kind: "pi",
        aliases: &["pi"],
        resume: Some(&["{exe}", "--session", "{sid}"]),
        cont: Some(&["{exe}", "-c"]),
    },
    Agent {
        kind: "gemini",
        aliases: &["gemini"],
        resume: Some(&["{exe}", "--resume", "{sid}"]),
        cont: Some(&["{exe}", "--continue"]),
    },
    Agent {
        kind: "opencode",
        aliases: &["opencode"],
        resume: Some(&["{exe}", "--session", "{sid}"]),
        cont: Some(&["{exe}", "--continue"]),
    },
    Agent {
        kind: "qwen",
        aliases: &["qwen"],
        resume: Some(&["{exe}", "--resume", "{sid}"]),
        cont: Some(&["{exe}", "--continue"]),
    },
    Agent {
        kind: "kimi",
        aliases: &["kimi"],
        resume: Some(&["{exe}", "--resume", "{sid}"]),
        cont: Some(&["{exe}", "--continue"]),
    },
    Agent {
        kind: "cursor",
        aliases: &["cursor-agent", "cursor"],
        resume: Some(&["{exe}", "--resume", "{sid}"]),
        cont: Some(&["{exe}", "--continue"]),
    },
    Agent {
        kind: "copilot",
        aliases: &["copilot"],
        resume: Some(&["{exe}", "--resume", "{sid}"]),
        cont: Some(&["{exe}", "--continue"]),
    },
    Agent {
        kind: "aider",
        aliases: &["aider"],
        resume: Some(&["{exe}", "--restore-chat-history"]),
        cont: Some(&["{exe}", "--restore-chat-history"]),
    },
];

pub fn detect(exe: &str) -> &'static str {
    let base = paths::base_name(std::path::Path::new(exe));
    for agent in AGENTS {
        if agent.aliases.iter().any(|alias| *alias == base) {
            return agent.kind;
        }
    }
    "generic"
}

pub fn spec_for(kind: &str) -> Option<&'static Agent> {
    AGENTS.iter().find(|agent| agent.kind == kind)
}

fn expand(template: &[&str], exe: &str, name: &str, sid: &str) -> Vec<String> {
    template
        .iter()
        .map(|part| {
            part.replace("{exe}", exe)
                .replace("{name}", name)
                .replace("{sid}", sid)
        })
        .collect()
}

fn argv_of(record: &Json) -> Vec<String> {
    record
        .get("argv")
        .and_then(|v| v.as_arr())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

pub fn session_id_of(record: &Json) -> Option<String> {
    record
        .get("session_id")
        .or_else(|| record.get("claude_sid"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
}

/// 生成恢复命令；返回 None 表示该会话无法恢复对话（只能重建进程）。
pub fn resume_argv(record: &Json) -> Option<Vec<String>> {
    let argv = argv_of(record);
    if argv.is_empty() {
        return None;
    }
    let exe = argv[0].clone();
    let kind = record
        .get("agent")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| detect(&exe).to_string());
    let name = record
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let spec = spec_for(&kind)?;
    let sid = session_id_of(record);
    if let (Some(sid), Some(template)) = (sid.as_deref(), spec.resume) {
        return Some(expand(template, &exe, name, sid));
    }
    spec.cont.map(|template| expand(template, &exe, name, sid.as_deref().unwrap_or("")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json;

    #[test]
    fn detects_kinds() {
        assert_eq!(detect("claude"), "claude");
        assert_eq!(detect("C:/tools/codex.exe"), "codex");
        assert_eq!(detect("cursor-agent"), "cursor");
        assert_eq!(detect("bash"), "generic");
    }

    #[test]
    fn claude_resume() {
        let record = json::parse(
            r#"{"name":"x","agent":"claude","session_id":"11111111-2222-3333-4444-555555555555","argv":["claude","--session-id","11111111-2222-3333-4444-555555555555"]}"#,
        )
        .unwrap();
        assert_eq!(
            resume_argv(&record).unwrap(),
            vec![
                "claude".to_string(),
                "--resume".to_string(),
                "11111111-2222-3333-4444-555555555555".to_string()
            ]
        );
    }

    #[test]
    fn codex_fallback_continue() {
        let record = json::parse(r#"{"name":"x","agent":"codex","argv":["codex"]}"#).unwrap();
        assert_eq!(
            resume_argv(&record).unwrap(),
            vec!["codex".to_string(), "resume".to_string(), "--last".to_string()]
        );
    }
}
