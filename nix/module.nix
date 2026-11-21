self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.manuscript-discovery;
  exe = lib.getExe cfg.package;
in
{
  options.services.manuscript-discovery = {
    enable = lib.mkEnableOption "the Manuscript Discovery web service";
    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
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
    host = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 8000;
    };
    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.manuscript-discovery = {
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      environment = {
        MANUSCRIPT_DB_PATH = cfg.dbPath;
        MANUSCRIPT_HOST = cfg.host;
        MANUSCRIPT_PORT = toString cfg.port;
      };
      serviceConfig = {
        ExecStartPre = lib.optional (cfg.sourceDir != null) "${exe} ingest ${cfg.sourceDir}";
        ExecStart = "${exe} serve";
        TimeoutStartSec = "1h"; # a first ingest of many translations takes a while
        Restart = "on-failure";
        DynamicUser = true;
        StateDirectory = "manuscript-discovery";
        # Typst runs as a child process on user-influenced input: keep the whole unit boxed in.
        ProtectSystem = "strict";
        ReadWritePaths = [ (builtins.dirOf cfg.dbPath) ];
        ReadOnlyPaths = lib.optional (cfg.sourceDir != null) (toString cfg.sourceDir);
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        NoNewPrivileges = true;
        CapabilityBoundingSet = "";
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
        SystemCallFilter = [
          "@system-service"
          "~@privileged"
        ];
        MemoryMax = "2G"; # ingest parses several large XML files in parallel
      };
    };
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
  };
}
