Name:           opencode-spend-watch
Version:        1.0.0
Release:        1%{?dist}
Summary:        Dollar and usage alerts for OpenCode, OpenRouter and OpenAI

License:        GPL-3.0-or-later
URL:            https://github.com/cusae/opencode-spend-watch
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
Requires:       python3 >= 3.10

%description
A small Python watcher that reads OpenCode, OpenRouter and OpenAI spend,
keeps a local history, and posts Mattermost, Slack, Discord, IRC, email,
WhatsApp, Telegram, desktop and RSS alerts when configurable dollar or
percentage thresholds are crossed.

%prep
%autosetup -n %{name}-%{version}

%build

%install
install -Dm755 packaging/opencode-spend-watch \
    %{buildroot}%{_bindir}/opencode-spend-watch
install -d %{buildroot}%{_prefix}/lib/opencode-spend-watch
install -Dm644 watch.py \
    %{buildroot}%{_prefix}/lib/opencode-spend-watch/watch.py
install -Dm644 notify.py \
    %{buildroot}%{_prefix}/lib/opencode-spend-watch/notify.py
install -Dm644 providers.py \
    %{buildroot}%{_prefix}/lib/opencode-spend-watch/providers.py
install -Dm644 limits.json \
    %{buildroot}%{_prefix}/lib/opencode-spend-watch/limits.json

%files
%{_bindir}/opencode-spend-watch
%{_prefix}/lib/opencode-spend-watch
%doc README.md CHANGELOG.md config.example.env metadata.json

%changelog
* Mon Nov 09 2026 Cusae <asl@launay.org> - 1.0.0-1
- Initial release.
