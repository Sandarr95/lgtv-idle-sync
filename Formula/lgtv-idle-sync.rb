class LgtvIdleSync < Formula
  desc "Sync idle state from a Linux desktop to an LG TV"
  homepage "https://github.com/Sandarr95/lgtv-idle-sync"
  url "file:///var/home/sander/Documenten/Projects/lgtv-idle-sync/dist/lgtv_idle_sync-0.2.0.tar.gz"
  sha256 "5b75081e4167cb91f208285ba0763c5d51a1d230aeda2ec937bb635d9df4ce68"

  depends_on "python@3.12"
  depends_on "uv" => :build          # we install the package + locked deps via uv
  depends_on "wayland" => :build     # pywayland's build needs wayland-scanner / wayland.xml

  def install
    # Use uv to create a venv inside the Cellar, then symlink binaries.
    # Going through uv (not Language::Python::Virtualenv) sidesteps brew's
    # superenv stripping include paths during cffi / Cython sdist builds —
    # uv prefers PyPI wheels, which don't need to compile.
    venv = libexec/"venv"
    ENV["UV_PROJECT_ENVIRONMENT"] = venv
    ENV["UV_PYTHON"] = Formula["python@3.12"].opt_bin/"python3.12"

    # --frozen pins to the uv.lock that ships in the sdist for reproducibility.
    # --no-editable installs the project as a regular package (not as a link
    # to the build dir, which brew throws away after install).
    system "uv", "sync", "--frozen", "--no-dev", "--no-editable"

    bin.install_symlink Dir["#{venv}/bin/lgtv-*"]
  end

  def caveats
    <<~CAVEATS
      To register KDE custom shortcuts (graceful suspend, screen off, screen on),
      run once after install:
        lgtv-install

      That step writes .desktop files into ~/.local/share/applications/ so the
      shortcuts are discoverable in System Settings → Shortcuts → Add Application.
      It runs outside brew because brew's install sandbox blocks writes to
      ~/.local and its post_install hook trips a path-validation bug on Bazzite
      (where /home is a symlink to /var/home).
    CAVEATS
  end

  test do
    assert_predicate bin/"lgtv-idle-sync", :executable?
    assert_predicate bin/"lgtv-graceful-suspend", :executable?
  end
end
