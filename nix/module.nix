{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.manuscript-discovery;
  exe = lib.getExe cfg.package;
  nginx = cfg.nginx;

  user = "manuscript-discovery";
  # nginx and the app meet here. The directory is 0750 and the socket 0660, both owned by the service's
  # user and group, and nginx joins that group (SupplementaryGroups below): nobody else can connect.
  socket = "/run/manuscript-discovery/app.sock";

  # Directives every proxied location shares. X-Forwarded-For is *set* to the peer address, not appended
  # to, so a client cannot seed it with an address of its choosing.
  proxy = ''
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 5s;
    proxy_send_timeout 10s;
    proxy_read_timeout ${nginx.readTimeout};
    proxy_next_upstream off;
    limit_except GET HEAD { deny all; }
  '';

  rootDir = "/var/lib/manuscript-discovery-root";
in
{
  options.services.manuscript-discovery = {
    enable = lib.mkEnableOption "the Manuscript Discovery web service";
    package = lib.mkOption {
      type = lib.types.package;
      default = (import ./default.nix { inherit pkgs; }).default;
      description = "The manuscript-discovery package to run.";
    };
    dbPath = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/manuscript-discovery/library.sqlite";
      description = "Library database. Built by ingest; opened read-only by the web app.";
    };
    sourceDir = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Folder of eBible *_usfx.zip files. When set, it is ingested before every start; files
        whose hash is unchanged are skipped, so only new or changed translations cost time.
      '';
    };
    settings = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      example = {
        max_waiting = "32";
        log_level = "warning";
      };
      description = "Any other application setting, as MANUSCRIPT_<NAME> environment variables (see settings.py).";
    };
    host = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Address to listen on. Unused with nginx.enable, which uses a Unix socket.";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 8000;
      description = "Port to listen on. Unused with nginx.enable, which uses a Unix socket.";
    };
    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the listening port: 80 and 443 with nginx.enable, otherwise the app's own port.";
    };

    nginx = {
      enable = lib.mkEnableOption ''
        a hardened nginx in front of the app. The app then listens on a Unix socket only (no TCP port,
        and a unit with no network at all), and nginx terminates TLS, redirects HTTP, rate-limits the
        expensive routes, restricts methods and hides the health endpoints'';
      domain = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "manuscripts.example.org";
        description = "The public host name nginx serves (server_name, and the ACME certificate's name).";
      };
      acme = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = ''
          Obtain and renew a Let's Encrypt certificate. This needs security.acme.acceptTerms and
          security.acme.defaults.email to be set, and port 80 reachable. With false, provide the
          certificate yourself on services.nginx.virtualHosts.<domain>.
        '';
      };
      rateLimit = {
        preview = lib.mkOption {
          type = lib.types.strMatching "[0-9]+r/[sm]";
          default = "5r/s";
          description = "Per-client rate for the live preview (bursts of 20 are allowed). The page asks at most about twice a second.";
        };
        pdf = lib.mkOption {
          type = lib.types.strMatching "[0-9]+r/[sm]";
          default = "10r/m";
          description = "Per-client rate for PDF downloads, the most expensive request (bursts of 5 are allowed). Plain-text requests do not count.";
        };
        other = lib.mkOption {
          type = lib.types.strMatching "[0-9]+r/[sm]";
          default = "30r/s";
          description = "Per-client rate for everything else (bursts of 60 are allowed).";
        };
      };
      readTimeout = lib.mkOption {
        type = lib.types.str;
        default = "45s";
        description = "How long nginx waits for the app. Keep it above MANUSCRIPT_TIMEOUT_S (default 30 s), which is how long one render may take.";
      };
    };
  };

  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        assertions = [
          {
            assertion = !nginx.enable || nginx.domain != null;
            message = "services.manuscript-discovery.nginx.enable needs services.manuscript-discovery.nginx.domain.";
          }
        ];

        users.users.${user} = {
          isSystemUser = true;
          group = user;
        };
        users.groups.${user} = { };

        systemd.services.manuscript-discovery = {
          wantedBy = [ "multi-user.target" ];
          after = lib.optional (!nginx.enable) "network.target";
          environment = {
            MANUSCRIPT_DB_PATH = cfg.dbPath;
          }
          // (
            if nginx.enable then
              { MANUSCRIPT_UNIX_SOCKET = socket; }
            else
              {
                MANUSCRIPT_HOST = cfg.host;
                MANUSCRIPT_PORT = toString cfg.port;
              }
          )
          // lib.mapAttrs' (
            name: value: lib.nameValuePair "MANUSCRIPT_${lib.toUpper name}" value
          ) cfg.settings;
          serviceConfig = {
            ExecStartPre = lib.optional (cfg.sourceDir != null) "${exe} ingest ${cfg.sourceDir}";
            ExecStart = "${exe} serve";
            TimeoutStartSec = "1h"; # a first ingest of many translations takes a while
            Restart = "on-failure";
            User = user;
            Group = user;
            StateDirectory = "manuscript-discovery";
            UMask = "0077";
            # Typst runs as a child process on user-influenced input: keep the whole unit boxed in.
            RootDirectory = rootDir;
            MountAPIVFS = true;
            BindReadOnlyPaths = [
              "/nix/store"
            ]
            ++ lib.optional (cfg.sourceDir != null) (toString cfg.sourceDir);
            BindPaths = lib.optional (builtins.dirOf cfg.dbPath != "/var/lib/manuscript-discovery") (
              builtins.dirOf cfg.dbPath
            );
            ProtectProc = "invisible";
            ProcSubset = "pid";
            StateDirectoryMode = "0700";
            WorkingDirectory = "/";
            ProtectSystem = "strict";
            ReadWritePaths = [ (builtins.dirOf cfg.dbPath) ];
            ReadOnlyPaths = lib.optional (cfg.sourceDir != null) (toString cfg.sourceDir);
            ProtectHome = true;
            PrivateTmp = "disconnected";
            PrivateDevices = true;
            NoNewPrivileges = true;
            CapabilityBoundingSet = "";
            ProtectKernelTunables = true;
            ProtectKernelModules = true;
            ProtectKernelLogs = true;
            ProtectControlGroups = true;
            ProtectClock = true;
            ProtectHostname = true;
            LockPersonality = true;
            RestrictRealtime = true;
            RestrictSUIDSGID = true;
            RestrictNamespaces = true;
            SystemCallArchitectures = "native";
            RemoveIPC = true;
            MemoryDenyWriteExecute = true;
            RestrictAddressFamilies =
              if nginx.enable then
                [ "AF_UNIX" ]
              else
                [
                  "AF_INET"
                  "AF_INET6"
                  "AF_UNIX"
                ];
            SystemCallFilter = [
              "@system-service"
              "~@privileged"
            ];
            CPUQuota = "200%";
            CPUWeight = 50;
            MemoryHigh = "1536M";
            MemoryMax = "2G";
            MemorySwapMax = "0";
            TasksMax = 128;
            IOWeight = 50;
            LimitNOFILE = 4096;
            LimitCORE = 0;
            LogRateLimitIntervalSec = "30s";
            LogRateLimitBurst = 200;
          }
          // lib.optionalAttrs nginx.enable {
            # Behind nginx the app needs no network at all: it, and every Typst it starts, run in an
            # empty network namespace and talk only through the socket.
            PrivateNetwork = true;
            IPAddressDeny = "any";
            RuntimeDirectory = "manuscript-discovery";
            RuntimeDirectoryMode = "0750";
          };
        };

        networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall (
          if nginx.enable then
            [
              80
              443
            ]
          else
            [ cfg.port ]
        );

        systemd.tmpfiles.rules = [
          "d ${rootDir} 0755 root root -"
        ];
      }

      # With no domain the assertion above explains; do not also trip over a null host name here.
      (lib.mkIf (nginx.enable && nginx.domain != null) {
        # Join the app's group for the socket. Done on nginx's unit (not by adding nginx to the group),
        # because a unit's groups are applied when it restarts, and changing this restarts it.
        systemd.services.nginx.serviceConfig.SupplementaryGroups = [ user ];

        services.nginx = {
          enable = true;
          # Defaults only (mkDefault): they are global nginx settings, so the host may override them.
          recommendedTlsSettings = lib.mkDefault true;
          recommendedGzipSettings = lib.mkDefault true;
          recommendedOptimisation = lib.mkDefault true;

          appendHttpConfig = ''
            # Per-client limits. Previews and PDFs get their own because a render is far dearer than
            # a lookup. Requests for plain text (?format=txt) map to an empty key, which is never counted.
            limit_req_zone $binary_remote_addr zone=md_other:10m rate=${nginx.rateLimit.other};
            limit_req_zone $binary_remote_addr zone=md_preview:10m rate=${nginx.rateLimit.preview};
            map $arg_format $md_pdf_key {
              default $binary_remote_addr;
              txt "";
            }
            limit_req_zone $md_pdf_key zone=md_pdf:10m rate=${nginx.rateLimit.pdf};
            limit_req_status 429;
            # Global limits
            limit_req_zone $server_name zone=md_global:1m rate=60r/s;
            limit_req_zone $server_name zone=md_preview_global:1m rate=10r/s;
            limit_req_zone $server_name zone=md_pdf_global:1m rate=30r/m;
            limit_conn_zone $server_name zone=md_connections:1m;
          '';

          upstreams.manuscript-discovery = {
            servers."unix:${socket}" = { };
            extraConfig = "keepalive 8;";
          };

          virtualHosts.${nginx.domain} = {
            enableACME = nginx.acme;
            forceSSL = true;
            extraConfig = ''
              add_header Strict-Transport-Security "max-age=31536000" always;
              client_max_body_size 1k;
              client_header_timeout 10s;
              client_body_timeout 10s;
              send_timeout 30s;
              keepalive_timeout 30s;
              limit_conn md_connections 32;
              limit_conn_status 429;
            '';
            locations = {
              "/" = {
                proxyPass = "http://manuscript-discovery";
                recommendedProxySettings = false;
                extraConfig = ''
                  ${proxy}
                  limit_req zone=md_other burst=60 nodelay;
                  limit_req zone=md_global burst=100 nodelay;
                '';
              };
              "= /api/preview" = {
                proxyPass = "http://manuscript-discovery";
                recommendedProxySettings = false;
                extraConfig = ''
                  ${proxy}
                  limit_req zone=md_preview burst=20 nodelay;
                  limit_req zone=md_preview_global burst=10 nodelay;
                '';
              };
              "= /api/render" = {
                proxyPass = "http://manuscript-discovery";
                recommendedProxySettings = false;
                extraConfig = ''
                  ${proxy}
                  limit_req zone=md_pdf burst=5 nodelay;
                  limit_req zone=md_other burst=60 nodelay;
                  limit_req zone=md_pdf_global burst=10 nodelay;
                '';
              };
              # Probes and diagnostics are for whoever runs the host, over the socket; not for the world.
              "~ ^/(healthz|readyz|api/health)$" = {
                return = "404";
              };
            };
          };
        };

      })
    ]
  );
}
