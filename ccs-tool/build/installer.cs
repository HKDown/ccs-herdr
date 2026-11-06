using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("ccs-tool installer")]
[assembly: AssemblyProduct("ccs-tool")]
[assembly: AssemblyVersion("0.1.0.0")]
[assembly: AssemblyFileVersion("0.1.0.0")]

namespace ccsSetup
{
    static class Log
    {
        static readonly string Path0 = Environment.GetEnvironmentVariable("CCS_SETUP_LOG");
        public static void W(string text)
        {
            if (string.IsNullOrEmpty(Path0)) return;
            try { File.AppendAllText(Path0, DateTime.Now.ToString("HH:mm:ss.fff") + " " + text + Environment.NewLine); }
            catch { }
        }
    }

    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            bool uninstall = false, silent = false, autostart = true, desktop = false;
            string dir = null;
            foreach (string a in args)
            {
                if (a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase)) uninstall = true;
                else if (a.Equals("/S", StringComparison.OrdinalIgnoreCase) || a.Equals("/silent", StringComparison.OrdinalIgnoreCase)) silent = true;
                else if (a.StartsWith("/DIR=", StringComparison.OrdinalIgnoreCase)) dir = a.Substring(5).Trim('"');
                else if (a.Equals("/noautostart", StringComparison.OrdinalIgnoreCase)) autostart = false;
                else if (a.Equals("/autostart", StringComparison.OrdinalIgnoreCase)) autostart = true;
                else if (a.Equals("/desktop", StringComparison.OrdinalIgnoreCase)) desktop = true;
            }
            bool isUninstaller = Path.GetFileName(Application.ExecutablePath).ToLowerInvariant().Contains("uninstall");
            Log.W("main args=" + string.Join(" ", args) + " uninstall=" + uninstall + " silent=" + silent + " dir=" + dir);
            try
            {
                if (uninstall || isUninstaller) { Uninstaller.Run(silent, dir); return; }
                if (silent) { new Installer(dir, autostart, desktop).Run(null); return; }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new InstallForm());
            }
            catch (Exception ex)
            {
                Log.W("FATAL " + ex);
                if (!silent) MessageBox.Show("操作失败:\n" + ex.Message, "ccs-tool", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    static class Native
    {
        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);

        public static void BroadcastEnvironmentChange()
        {
            IntPtr result;
            SendMessageTimeout((IntPtr)0xFFFF, 0x001A, IntPtr.Zero, "Environment", 0x0002, 3000, out result);
        }
    }

    static class AppInfo
    {
        public const string Name = "ccs-tool";
        public const string Version = "0.3.1";
        public const string Publisher = "ccs-tool";
        public const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\ccs-tool";

        public static string DefaultDir
        {
            get
            {
                return Path.Combine(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs"), "ccs");
            }
        }

        public static string ExePath(string dir) { return Path.Combine(dir, "ccs.exe"); }

        public static string StartMenuLink
        {
            get
            {
                return Path.Combine(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    @"Microsoft\Windows\Start Menu\Programs"), "ccs-tool.lnk");
            }
        }

        public static string DesktopLink
        {
            get
            {
                return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "ccs-tool.lnk");
            }
        }
    }

    static class Sys
    {
        public static string Run(string exe, string args, int timeoutMs)
        {
            Log.W("run-start: " + exe + " " + args);
            try
            {
                Log.W("run: " + exe + " " + args);
                ProcessStartInfo psi = new ProcessStartInfo(exe, args);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                using (Process p = Process.Start(psi))
                {
                    string so = p.StandardOutput.ReadToEnd();
                    string se = p.StandardError.ReadToEnd();
                    if (!p.WaitForExit(timeoutMs)) { try { p.Kill(); } catch { } return so + se; }
                    return so + se;
                }
            }
            catch (Exception ex) { return ex.Message; }
        }

        public static void AddToUserPath(string dir)
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey("Environment"))
            {
                string cur = (key.GetValue("Path", "", RegistryValueOptions.DoNotExpandEnvironmentNames) as string) ?? "";
                string norm = dir.TrimEnd('\\');
                foreach (string part in cur.Split(';'))
                {
                    if (part.Trim().TrimEnd('\\').Equals(norm, StringComparison.OrdinalIgnoreCase)) return;
                }
                string newValue = string.IsNullOrWhiteSpace(cur) ? dir : cur.TrimEnd(';') + ";" + dir;
                key.SetValue("Path", newValue, RegistryValueKind.ExpandString);
            }
            Native.BroadcastEnvironmentChange();
        }

        public static void RemoveFromUserPath(string dir)
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey("Environment", true))
            {
                if (key == null) return;
                string cur = (key.GetValue("Path", "", RegistryValueOptions.DoNotExpandEnvironmentNames) as string) ?? "";
                string norm = dir.TrimEnd('\\');
                List<string> kept = new List<string>();
                bool changed = false;
                foreach (string part in cur.Split(';'))
                {
                    if (part.Trim().TrimEnd('\\').Equals(norm, StringComparison.OrdinalIgnoreCase)) { changed = true; continue; }
                    if (part.Trim().Length > 0) kept.Add(part);
                }
                if (changed) { key.SetValue("Path", string.Join(";", kept.ToArray()), RegistryValueKind.ExpandString); Native.BroadcastEnvironmentChange(); }
            }
        }

        public static void CreateShortcut(string linkPath, string target, string workDir, string description, string iconPath, string arguments = null)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(shellType);
            object link = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { linkPath });
            Type linkType = link.GetType();
            linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { target });
            if (!string.IsNullOrEmpty(arguments))
                linkType.InvokeMember("Arguments", BindingFlags.SetProperty, null, link, new object[] { arguments });
            linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { workDir });
            linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { description });
            linkType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { iconPath });
            linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
            Marshal.ReleaseComObject(link);
            Marshal.ReleaseComObject(shell);
        }

        public static void DeleteFileSafe(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); } catch { }
        }

        public static string FindOnPath(string name)
        {
            string path = Environment.GetEnvironmentVariable("Path") ?? "";
            foreach (string part in path.Split(';'))
            {
                if (string.IsNullOrWhiteSpace(part)) continue;
                try
                {
                    string full = Path.Combine(part.Trim(), name);
                    if (File.Exists(full)) return full;
                }
                catch { }
            }
            return null;
        }

        public static void CopyDirectory(string source, string target)
        {
            Directory.CreateDirectory(target);
            foreach (string file in Directory.GetFiles(source))
            {
                File.Copy(file, Path.Combine(target, Path.GetFileName(file)), true);
            }
            foreach (string sub in Directory.GetDirectories(source))
            {
                CopyDirectory(sub, Path.Combine(target, Path.GetFileName(sub)));
            }
        }
    }

    class Installer
    {
        readonly string dir;
        readonly bool autostart;
        readonly bool desktop;
        public readonly List<string> Warnings = new List<string>();

        public Installer(string targetDir, bool autostart, bool desktopShortcut)
        {
            dir = string.IsNullOrWhiteSpace(targetDir) ? AppInfo.DefaultDir : Path.GetFullPath(targetDir);
            this.autostart = autostart;
            this.desktop = desktopShortcut;
        }

        public string TargetDir { get { return dir; } }

        public void Run(Action<string, int> progress)
        {
            Report(progress, "停止正在运行的 ccs 守护进程…", 5);
            if (File.Exists(AppInfo.ExePath(dir))) Sys.Run(AppInfo.ExePath(dir), "daemon stop", 15000);

            Report(progress, "创建安装目录…", 10);
            if (Directory.Exists(dir))
            {
                try { Directory.Delete(dir, true); }
                catch (Exception ex) { Warnings.Add("无法清空旧目录（可能仍被占用）: " + ex.Message); }
            }
            Directory.CreateDirectory(dir);

            Report(progress, "解压程序文件…", 25);
            ExtractPayload(dir);

            Report(progress, "创建开始菜单快捷方式…", 65);
            try
            {
                Sys.CreateShortcut(AppInfo.StartMenuLink, AppInfo.ExePath(dir), dir,
                    "ccs-tool — Windows 上的 tmux for Claude CLI", AppInfo.ExePath(dir));
                Sys.CreateShortcut(Path.Combine(Path.GetDirectoryName(AppInfo.StartMenuLink), "ccs 控制台.lnk"),
                    AppInfo.ExePath(dir), dir, "ccs-tool 可视化控制台（浏览器）", AppInfo.ExePath(dir), "web --open");
            }
            catch (Exception ex) { Warnings.Add("开始菜单快捷方式失败: " + ex.Message); }

            if (desktop)
            {
                Report(progress, "创建桌面快捷方式…", 70);
                try
                {
                    Sys.CreateShortcut(AppInfo.DesktopLink, AppInfo.ExePath(dir), dir,
                        "ccs-tool — Windows 上的 tmux for Claude CLI", AppInfo.ExePath(dir));
                }
                catch (Exception ex) { Warnings.Add("桌面快捷方式失败: " + ex.Message); }
            }

            Report(progress, "写入用户 PATH…", 78);
            try { Sys.AddToUserPath(dir); }
            catch (Exception ex) { Warnings.Add("写入用户 PATH 失败: " + ex.Message); }

            Report(progress, "注册卸载信息…", 85);
            WriteUninstallEntry();

            Report(progress, "配置开机自启…", 92);
            try
            {
                string output = Sys.Run(AppInfo.ExePath(dir), autostart ? "autostart on" : "autostart off", 15000);
                if (autostart && output.IndexOf("失败", StringComparison.Ordinal) >= 0) Warnings.Add("开机自启可能失败: " + output.Trim());
            }
            catch (Exception ex) { Warnings.Add("开机自启配置失败: " + ex.Message); }

            Report(progress, "完成", 100);
        }

        static void Report(Action<string, int> progress, string text, int percent)
        {
            Log.W("step " + percent + "% " + text);
            if (progress != null) progress(text, percent);
        }

        void ExtractPayload(string target)
        {
            using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            {
                if (resource == null) throw new InvalidOperationException("安装包损坏：找不到 payload.zip 资源");
                string tempZip = Path.Combine(Path.GetTempPath(), "ccs-payload-" + Guid.NewGuid().ToString("N") + ".zip");
                using (FileStream fs = File.Create(tempZip)) resource.CopyTo(fs);
                try
                {
                    using (ZipArchive zip = ZipFile.OpenRead(tempZip))
                    {
                        foreach (ZipArchiveEntry entry in zip.Entries)
                        {
                            string rel = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                            string dest = Path.GetFullPath(Path.Combine(target, rel));
                            if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(dest); continue; }
                            Directory.CreateDirectory(Path.GetDirectoryName(dest));
                            entry.ExtractToFile(dest, true);
                        }
                    }
                }
                finally { try { File.Delete(tempZip); } catch { } }
            }
        }

        void WriteUninstallEntry()
        {
            try
            {
                long size = 0;
                try
                {
                    foreach (string f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
                        size += new FileInfo(f).Length;
                }
                catch { }
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(AppInfo.UninstallKey))
                {
                    key.SetValue("DisplayName", AppInfo.Name);
                    key.SetValue("DisplayVersion", AppInfo.Version);
                    key.SetValue("Publisher", AppInfo.Publisher);
                    key.SetValue("InstallLocation", dir);
                    key.SetValue("DisplayIcon", AppInfo.ExePath(dir));
                    key.SetValue("UninstallString", "\"" + Path.Combine(dir, "ccs-uninstall.exe") + "\" /uninstall");
                    key.SetValue("QuietUninstallString", "\"" + Path.Combine(dir, "ccs-uninstall.exe") + "\" /uninstall /S");
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    key.SetValue("EstimatedSize", (int)(size / 1024), RegistryValueKind.DWord);
                }
            }
            catch (Exception ex) { Warnings.Add("卸载信息写入失败: " + ex.Message); }
        }
    }

    class Uninstaller
    {
        public static void Run(bool silent, string targetDir)
        {
            string dir = string.IsNullOrWhiteSpace(targetDir)
                ? Path.GetDirectoryName(Application.ExecutablePath)
                : Path.GetFullPath(targetDir);
            string exe = AppInfo.ExePath(dir);
            if (File.Exists(exe))
            {
                Sys.Run(exe, "autostart off", 15000);
                Sys.Run(exe, "daemon stop", 15000);
            }
            try { Sys.RemoveFromUserPath(dir); } catch { }
            Sys.DeleteFileSafe(AppInfo.StartMenuLink);
            Sys.DeleteFileSafe(Path.Combine(Path.GetDirectoryName(AppInfo.StartMenuLink), "ccs 控制台.lnk"));
            Sys.DeleteFileSafe(AppInfo.DesktopLink);
            try { Registry.CurrentUser.DeleteSubKeyTree(AppInfo.UninstallKey, false); } catch { }

            string script = Path.Combine(Path.GetTempPath(), "ccs-uninstall-" + Guid.NewGuid().ToString("N") + ".cmd");
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("@echo off");
            sb.AppendLine("timeout /t 2 /nobreak >nul");
            sb.AppendLine("rmdir /s /q \"" + dir + "\"");
            sb.AppendLine("del /f /q \"%~f0\"");
            File.WriteAllText(script, sb.ToString(), Encoding.Default);
            ProcessStartInfo psi = new ProcessStartInfo("cmd.exe", "/c \"" + script + "\"");
            psi.CreateNoWindow = true;
            psi.UseShellExecute = false;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(psi);

            if (!silent) MessageBox.Show("ccs-tool 已卸载。", "ccs-tool", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

    class InstallForm : Form
    {
        readonly TextBox pathBox = new TextBox();
        readonly CheckBox autoBox = new CheckBox();
        readonly CheckBox deskBox = new CheckBox();
        readonly Button installButton = new Button();
        readonly Button browseButton = new Button();
        readonly ProgressBar bar = new ProgressBar();
        readonly Label status = new Label();

        public InstallForm()
        {
            Text = "ccs-tool 安装程序";
            ClientSize = new Size(560, 330);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 9F);

            Label title = new Label();
            title.Text = "ccs-tool  " + AppInfo.Version;
            title.Font = new Font("Microsoft YaHei UI", 14F, FontStyle.Bold);
            title.Location = new Point(20, 18);
            title.Size = new Size(520, 32);

            Label subtitle = new Label();
            subtitle.Text = "Windows 上的 tmux for Claude CLI：命名会话、关窗不丢、重启可恢复、多 agent 互通。";
            subtitle.Location = new Point(22, 52);
            subtitle.Size = new Size(520, 40);

            Label lblDir = new Label();
            lblDir.Text = "安装位置：";
            lblDir.Location = new Point(22, 100);
            lblDir.Size = new Size(80, 20);

            pathBox.Text = AppInfo.DefaultDir;
            pathBox.Location = new Point(22, 122);
            pathBox.Size = new Size(430, 26);

            browseButton.Text = "浏览…";
            browseButton.Location = new Point(458, 121);
            browseButton.Size = new Size(78, 26);
            browseButton.Click += delegate
            {
                FolderBrowserDialog dialog = new FolderBrowserDialog();
                dialog.Description = "选择 ccs-tool 安装目录";
                dialog.SelectedPath = pathBox.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK) pathBox.Text = dialog.SelectedPath;
            };

            autoBox.Text = "登录 Windows 时自动启动守护进程并恢复会话（推荐）";
            autoBox.Location = new Point(22, 160);
            autoBox.Size = new Size(500, 24);
            autoBox.Checked = true;

            deskBox.Text = "创建桌面快捷方式";
            deskBox.Location = new Point(22, 186);
            deskBox.Size = new Size(300, 24);
            deskBox.Checked = false;

            bar.Location = new Point(22, 222);
            bar.Size = new Size(514, 18);
            bar.Minimum = 0;
            bar.Maximum = 100;

            status.Text = "准备就绪。点击“安装”开始。";
            status.Location = new Point(22, 246);
            status.Size = new Size(514, 20);

            installButton.Text = "安装";
            installButton.Location = new Point(366, 280);
            installButton.Size = new Size(80, 30);
            installButton.Click += InstallClick;

            Button cancelButton = new Button();
            cancelButton.Text = "退出";
            cancelButton.Location = new Point(456, 280);
            cancelButton.Size = new Size(80, 30);
            cancelButton.Click += delegate { Close(); };

            Controls.Add(title);
            Controls.Add(subtitle);
            Controls.Add(lblDir);
            Controls.Add(pathBox);
            Controls.Add(browseButton);
            Controls.Add(autoBox);
            Controls.Add(deskBox);
            Controls.Add(bar);
            Controls.Add(status);
            Controls.Add(installButton);
            Controls.Add(cancelButton);
        }

        void InstallClick(object sender, EventArgs e)
        {
            string target = pathBox.Text.Trim();
            if (target.Length == 0) { MessageBox.Show("请填写安装目录。"); return; }
            installButton.Enabled = false;
            browseButton.Enabled = false;
            pathBox.Enabled = false;
            autoBox.Enabled = false;
            deskBox.Enabled = false;

            Installer installer = new Installer(target, autoBox.Checked, deskBox.Checked);
            Task.Run(delegate
            {
                try
                {
                    installer.Run(delegate (string text, int percent)
                    {
                        try
                        {
                            BeginInvoke(new Action(delegate
                            {
                                status.Text = text;
                                bar.Value = Math.Max(0, Math.Min(100, percent));
                            }));
                        }
                        catch { }
                    });
                    BeginInvoke(new Action(delegate { Finish(installer); }));
                }
                catch (Exception ex)
                {
                    BeginInvoke(new Action(delegate
                    {
                        MessageBox.Show("安装失败:\n" + ex.Message, "ccs-tool", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        installButton.Enabled = true;
                        browseButton.Enabled = true;
                        pathBox.Enabled = true;
                        autoBox.Enabled = true;
                        deskBox.Enabled = true;
                    }));
                }
            });
        }

        void Finish(Installer installer)
        {
            bar.Value = 100;
            status.Text = "安装完成。";
            string message = "ccs-tool 已安装到:\n" + installer.TargetDir +
                "\n\n请重新打开一个终端（让 PATH 生效），然后运行:\n  ccs daemon start\n  ccs new claude1 -- claude" +
                "\n\nHerdr 集成已拆到独立项目 ccs-herdr（Rust，跨平台），见其 README。";
            if (installer.Warnings.Count > 0)
            {
                message += "\n\n以下步骤有警告（不影响主程序使用）:";
                foreach (string w in installer.Warnings) message += "\n- " + w;
            }
            MessageBox.Show(message, "ccs-tool 安装完成", MessageBoxButtons.OK, MessageBoxIcon.Information);
            Close();
        }
    }
}
