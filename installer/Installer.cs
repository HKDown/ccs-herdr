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

[assembly: AssemblyTitle("ccs-herdr installer")]
[assembly: AssemblyProduct("ccs-herdr")]
[assembly: AssemblyVersion("0.2.0.0")]
[assembly: AssemblyFileVersion("0.2.0.0")]

namespace ccsHerdrSetup
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            bool uninstall = false, silent = false, herdr = false, desktop = false;
            string dir = null;
            foreach (string a in args)
            {
                if (a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase)) uninstall = true;
                else if (a.Equals("/S", StringComparison.OrdinalIgnoreCase) || a.Equals("/silent", StringComparison.OrdinalIgnoreCase)) silent = true;
                else if (a.StartsWith("/DIR=", StringComparison.OrdinalIgnoreCase)) dir = a.Substring(5).Trim('"');
                else if (a.Equals("/herdr", StringComparison.OrdinalIgnoreCase)) herdr = true;
                else if (a.Equals("/desktop", StringComparison.OrdinalIgnoreCase)) desktop = true;
            }
            bool isUninstaller = Path.GetFileName(Application.ExecutablePath).ToLowerInvariant().Contains("uninstall");
            Log.W("main args=" + string.Join(" ", args));
            try
            {
                if (uninstall || isUninstaller) { Uninstaller.Run(silent, dir); return; }
                if (silent) { new Installer(dir, herdr, desktop).Run(null); return; }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new InstallForm());
            }
            catch (Exception ex)
            {
                Log.W("FATAL " + ex);
                if (!silent) MessageBox.Show("操作失败:\n" + ex.Message, "ccs-herdr", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    static class Log
    {
        static readonly string Path0 = Environment.GetEnvironmentVariable("CCS_SETUP_LOG");
        public static void W(string text)
        {
            if (string.IsNullOrEmpty(Path0)) return;
            try { File.AppendAllText(Path0, DateTime.Now.ToString("HH:mm:ss.fff") + " " + text + Environment.NewLine); } catch { }
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
        public const string Name = "ccs-herdr";
        public const string Version = "0.2.0";
        public const string Publisher = "ccs-herdr";
        public const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\ccs-herdr";
        public const string HerdrVersion = "ccs 0.3.1 + ccs-herdr 0.1.0";

        public static string DefaultDir
        {
            get
            {
                return Path.Combine(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs"), "ccs-herdr");
            }
        }

        public static string EngineDir(string dir) { return Path.Combine(dir, "engine"); }
        public static string EngineExe(string dir) { return Path.Combine(EngineDir(dir), "ccs.exe"); }
        public static string BridgeExe(string dir) { return Path.Combine(dir, "ccs-herdr.exe"); }
        public static string PluginDir(string dir) { return Path.Combine(dir, "plugin"); }

        public static string StartMenuDir
        {
            get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), @"Microsoft\Windows\Start Menu\Programs"); }
        }
        public static string DesktopDir { get { return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory); } }
    }

    static class Sys
    {
        public static string Run(string exe, string args, int timeoutMs)
        {
            Log.W("run: " + exe + " " + args);
            try
            {
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

        public static void CreateShortcut(string linkPath, string target, string workDir, string description, string iconPath, string arguments)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(shellType);
            object link = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { linkPath });
            Type linkType = link.GetType();
            linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { target });
            linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { workDir });
            linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { description });
            if (!string.IsNullOrEmpty(iconPath)) linkType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { iconPath });
            if (!string.IsNullOrEmpty(arguments)) linkType.InvokeMember("Arguments", BindingFlags.SetProperty, null, link, new object[] { arguments });
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
    }

    class Installer
    {
        readonly string dir;
        readonly bool installHerdr;
        readonly bool desktop;
        public readonly List<string> Warnings = new List<string>();

        public Installer(string targetDir, bool installHerdr, bool desktopShortcut)
        {
            dir = string.IsNullOrWhiteSpace(targetDir) ? AppInfo.DefaultDir : Path.GetFullPath(targetDir);
            this.installHerdr = installHerdr;
            this.desktop = desktopShortcut;
        }

        public string TargetDir { get { return dir; } }

        public void Run(Action<string, int> progress)
        {
            Report(progress, "停止旧的 ccs 守护进程…", 5);
            if (File.Exists(AppInfo.EngineExe(dir))) Sys.Run(AppInfo.EngineExe(dir), "daemon stop", 15000);

            Report(progress, "创建安装目录…", 10);
            if (Directory.Exists(dir))
            {
                try { Directory.Delete(dir, true); }
                catch (Exception ex) { Warnings.Add("无法清空旧目录（可能仍被占用）: " + ex.Message); }
            }
            Directory.CreateDirectory(dir);

            Report(progress, "解压程序文件（内含 ccs 引擎）…", 25);
            ExtractPayload(dir);

            Report(progress, "写入用户 PATH…", 55);
            try
            {
                Sys.AddToUserPath(dir);
                Sys.AddToUserPath(AppInfo.EngineDir(dir));
            }
            catch (Exception ex) { Warnings.Add("写入用户 PATH 失败（可手动添加）: " + ex.Message); }

            Report(progress, "创建快捷方式…", 65);
            try
            {
                Sys.CreateShortcut(Path.Combine(AppInfo.StartMenuDir, "ccs 控制台.lnk"),
                    AppInfo.EngineExe(dir), dir, "ccs 可视化控制台（浏览器）", AppInfo.EngineExe(dir), "web --open");
                Sys.CreateShortcut(Path.Combine(AppInfo.StartMenuDir, "ccs-herdr 面板.lnk"),
                    AppInfo.BridgeExe(dir), dir, "ccs 会话面板", AppInfo.BridgeExe(dir), "pane");
                if (desktop)
                {
                    Sys.CreateShortcut(Path.Combine(AppInfo.DesktopDir, "ccs-herdr 面板.lnk"),
                        AppInfo.BridgeExe(dir), dir, "ccs 会话面板", AppInfo.BridgeExe(dir), "pane");
                }
            }
            catch (Exception ex) { Warnings.Add("创建快捷方式失败: " + ex.Message); }

            Report(progress, "注册卸载信息…", 72);
            WriteUninstallEntry();

            Report(progress, "检查 Herdr…", 80);
            string herdrExe = Sys.FindOnPath("herdr.exe");
            if (herdrExe == null)
            {
                if (installHerdr)
                {
                    Report(progress, "安装 Herdr（需要网络）…", 84);
                    string output = Sys.Run("powershell.exe",
                        "-NoProfile -ExecutionPolicy Bypass -Command \"irm https://herdr.dev/install.ps1 | iex\"", 300000);
                    herdrExe = Sys.FindOnPath("herdr.exe");
                    if (herdrExe == null) Warnings.Add("Herdr 自动安装未成功，请手动安装后运行 ccs-herdr install-plugin");
                    else Warnings.Add("已安装 Herdr: " + output.Trim());
                }
                else
                {
                    Warnings.Add("未检测到 Herdr：装好 Herdr 后运行 ccs-herdr install-plugin");
                }
            }

            Report(progress, "链接 Herdr 插件…", 90);
            if (herdrExe != null)
            {
                string linkOut = Sys.Run(AppInfo.BridgeExe(dir), "install-plugin", 60000);
                Warnings.Add("Herdr 插件链接结果: " + linkOut.Trim());
            }

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
                if (resource == null) throw new InvalidOperationException("安装包损坏：找不到 payload.zip");
                string tempZip = Path.Combine(Path.GetTempPath(), "ccs-herdr-payload-" + Guid.NewGuid().ToString("N") + ".zip");
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
                try { foreach (string f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories)) size += new FileInfo(f).Length; } catch { }
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(AppInfo.UninstallKey))
                {
                    key.SetValue("DisplayName", "ccs-herdr（含 ccs 引擎）");
                    key.SetValue("DisplayVersion", AppInfo.Version + " / " + AppInfo.HerdrVersion);
                    key.SetValue("Publisher", AppInfo.Publisher);
                    key.SetValue("InstallLocation", dir);
                    key.SetValue("DisplayIcon", AppInfo.BridgeExe(dir));
                    key.SetValue("UninstallString", "\"" + Path.Combine(dir, "ccs-herdr-uninstall.exe") + "\" /uninstall");
                    key.SetValue("QuietUninstallString", "\"" + Path.Combine(dir, "ccs-herdr-uninstall.exe") + "\" /uninstall /S");
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
            if (File.Exists(AppInfo.EngineExe(dir)))
            {
                Sys.Run(AppInfo.EngineExe(dir), "daemon stop", 15000);
            }
            try { Sys.RemoveFromUserPath(dir); } catch { }
            try { Sys.RemoveFromUserPath(AppInfo.EngineDir(dir)); } catch { }
            Sys.DeleteFileSafe(Path.Combine(AppInfo.StartMenuDir, "ccs 控制台.lnk"));
            Sys.DeleteFileSafe(Path.Combine(AppInfo.StartMenuDir, "ccs-herdr 面板.lnk"));
            Sys.DeleteFileSafe(Path.Combine(AppInfo.DesktopDir, "ccs-herdr 面板.lnk"));
            try { Registry.CurrentUser.DeleteSubKeyTree(AppInfo.UninstallKey, false); } catch { }
            // 尽量移除 Herdr 插件链接（有 herdr 时可手动再执行 herdr plugin uninstall）
            string herdr = Sys.FindOnPath("herdr.exe");
            if (herdr != null)
            {
                Sys.Run(herdr, "plugin uninstall ccs.sessions", 30000);
            }

            string script = Path.Combine(Path.GetTempPath(), "ccs-herdr-uninstall-" + Guid.NewGuid().ToString("N") + ".cmd");
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

            if (!silent) MessageBox.Show("ccs-herdr 已卸载。", "ccs-herdr", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

    class InstallForm : Form
    {
        readonly TextBox pathBox = new TextBox();
        readonly CheckBox herdrBox = new CheckBox();
        readonly CheckBox deskBox = new CheckBox();
        readonly Button installButton = new Button();
        readonly Button browseButton = new Button();
        readonly ProgressBar bar = new ProgressBar();
        readonly Label status = new Label();

        public InstallForm()
        {
            Text = "ccs-herdr 安装程序";
            ClientSize = new Size(600, 360);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 9F);

            Label title = new Label();
            title.Text = "ccs-herdr " + AppInfo.Version;
            title.Font = new Font("Microsoft YaHei UI", 14F, FontStyle.Bold);
            title.Location = new Point(20, 18);
            title.Size = new Size(560, 32);

            Label subtitle = new Label();
            subtitle.Text = "一次安装全部：ccs 引擎（会话/恢复/总线）+ ccs-herdr（Herdr 桥接与插件）。";
            subtitle.Location = new Point(22, 52);
            subtitle.Size = new Size(560, 40);

            Label lblDir = new Label();
            lblDir.Text = "安装位置：";
            lblDir.Location = new Point(22, 100);
            lblDir.Size = new Size(80, 20);

            pathBox.Text = AppInfo.DefaultDir;
            pathBox.Location = new Point(22, 122);
            pathBox.Size = new Size(470, 26);

            browseButton.Text = "浏览…";
            browseButton.Location = new Point(498, 121);
            browseButton.Size = new Size(78, 26);
            browseButton.Click += delegate
            {
                FolderBrowserDialog dialog = new FolderBrowserDialog();
                dialog.Description = "选择 ccs-herdr 安装目录";
                dialog.SelectedPath = pathBox.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK) pathBox.Text = dialog.SelectedPath;
            };

            herdrBox.Text = "同时安装 Herdr（需要网络；已安装则自动跳过）";
            herdrBox.Location = new Point(22, 160);
            herdrBox.Size = new Size(540, 24);
            herdrBox.Checked = Sys.FindOnPath("herdr.exe") == null;

            deskBox.Text = "创建桌面快捷方式";
            deskBox.Location = new Point(22, 186);
            deskBox.Size = new Size(300, 24);
            deskBox.Checked = false;

            bar.Location = new Point(22, 222);
            bar.Size = new Size(554, 18);
            bar.Minimum = 0;
            bar.Maximum = 100;

            status.Text = "准备就绪。点击“安装”开始。";
            status.Location = new Point(22, 246);
            status.Size = new Size(554, 20);

            installButton.Text = "安装";
            installButton.Location = new Point(406, 292);
            installButton.Size = new Size(80, 30);
            installButton.Click += InstallClick;

            Button cancelButton = new Button();
            cancelButton.Text = "退出";
            cancelButton.Location = new Point(496, 292);
            cancelButton.Size = new Size(80, 30);
            cancelButton.Click += delegate { Close(); };

            Controls.Add(title);
            Controls.Add(subtitle);
            Controls.Add(lblDir);
            Controls.Add(pathBox);
            Controls.Add(browseButton);
            Controls.Add(herdrBox);
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
            herdrBox.Enabled = false;
            deskBox.Enabled = false;

            Installer installer = new Installer(target, herdrBox.Checked, deskBox.Checked);
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
                        MessageBox.Show("安装失败:\n" + ex.Message, "ccs-herdr", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        installButton.Enabled = true;
                        browseButton.Enabled = true;
                        pathBox.Enabled = true;
                        herdrBox.Enabled = true;
                        deskBox.Enabled = true;
                    }));
                }
            });
        }

        void Finish(Installer installer)
        {
            bar.Value = 100;
            status.Text = "安装完成。";
            string message = "ccs-herdr 已安装到:\n" + installer.TargetDir +
                "\n\n请重新打开一个终端（让 PATH 生效），然后运行:\n  ccs-herdr doctor\n  ccs-herdr open";
            if (installer.Warnings.Count > 0)
            {
                message += "\n\n提示:";
                foreach (string w in installer.Warnings) message += "\n- " + w;
            }
            MessageBox.Show(message, "ccs-herdr 安装完成", MessageBoxButtons.OK, MessageBoxIcon.Information);
            Close();
        }
    }
}
