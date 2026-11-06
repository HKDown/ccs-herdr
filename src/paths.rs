//! 路径解析：跨平台（Windows / Linux / macOS），零依赖。

use std::env;
use std::path::{Path, PathBuf};

pub fn home() -> Option<PathBuf> {
    env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
}

/// ccs 状态目录：CCS_HOME，否则 ~/.ccs（与 ccs 本体一致）。
pub fn ccs_home() -> PathBuf {
    if let Some(v) = env::var_os("CCS_HOME") {
        if !v.is_empty() {
            return PathBuf::from(v);
        }
    }
    home().map(|h| h.join(".ccs")).unwrap_or_else(|| PathBuf::from(".ccs"))
}

/// ccs-herdr 自己的数据目录（与 ccs、其他项目隔离）：
///   Windows: %APPDATA%\ccs-herdr
///   macOS:   ~/Library/Application Support/ccs-herdr
///   Linux:   $XDG_CONFIG_HOME/ccs-herdr 或 ~/.config/ccs-herdr
/// 可用 CCS_HERDR_HOME 覆盖。
pub fn data_dir() -> PathBuf {
    if let Some(v) = env::var_os("CCS_HERDR_HOME") {
        if !v.is_empty() {
            return PathBuf::from(v);
        }
    }
    default_data_dir(
        env::var_os("APPDATA").map(PathBuf::from),
        env::var_os("XDG_CONFIG_HOME").map(PathBuf::from),
        home(),
        cfg!(windows),
        cfg!(target_os = "macos"),
    )
}

pub fn default_data_dir(
    appdata: Option<PathBuf>,
    xdg: Option<PathBuf>,
    home: Option<PathBuf>,
    windows: bool,
    macos: bool,
) -> PathBuf {
    if windows {
        if let Some(base) = appdata {
            return base.join("ccs-herdr");
        }
    } else if macos {
        if let Some(h) = home {
            return h.join("Library").join("Application Support").join("ccs-herdr");
        }
    } else if let Some(base) = xdg {
        return base.join("ccs-herdr");
    }
    home.map(|h| h.join(".config").join("ccs-herdr"))
        .unwrap_or_else(|| PathBuf::from(".ccs-herdr"))
}

pub fn map_file() -> PathBuf {
    data_dir().join("herdr-map.json")
}

/// 去掉目录/扩展名，返回小写命令名。
pub fn base_name(path: &Path) -> String {
    let name = path
        .file_name()
        .map(|s| s.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    for suffix in [".exe", ".cmd", ".bat", ".ps1"] {
        if let Some(stripped) = name.strip_suffix(suffix) {
            return stripped.to_string();
        }
    }
    name
}

/// 在 PATH 里查找可执行文件（Windows 会尝试 .exe/.cmd/.bat）。
pub fn which(name: &str) -> Option<PathBuf> {
    let path = env::var_os("PATH")?;
    let seps: &[char] = if cfg!(windows) { &[';'] } else { &[':'] };
    let suffixes: &[&str] = if cfg!(windows) {
        &["", ".exe", ".cmd", ".bat"]
    } else {
        &[""]
    };
    for dir in env::split_paths(&path) {
        for suffix in suffixes {
            let candidate = dir.join(format!("{name}{suffix}"));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    let _ = seps;
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn data_dir_per_platform() {
        let home = Some(PathBuf::from("/home/u"));
        assert_eq!(
            default_data_dir(Some(PathBuf::from("C:/Users/u/AppData/Roaming")), None, home.clone(), true, false),
            PathBuf::from("C:/Users/u/AppData/Roaming").join("ccs-herdr")
        );
        assert_eq!(
            default_data_dir(None, None, home.clone(), false, true),
            PathBuf::from("/home/u/Library/Application Support/ccs-herdr")
        );
        assert_eq!(
            default_data_dir(None, Some(PathBuf::from("/home/u/.config")), home.clone(), false, false),
            PathBuf::from("/home/u/.config/ccs-herdr")
        );
        assert_eq!(
            default_data_dir(None, None, home, false, false),
            PathBuf::from("/home/u/.config/ccs-herdr")
        );
    }

    #[test]
    fn base_name_strips() {
        assert_eq!(base_name(Path::new("claude.exe")), "claude");
        assert_eq!(base_name(Path::new("C:/x/Codex.CMD")), "codex");
    }
}
