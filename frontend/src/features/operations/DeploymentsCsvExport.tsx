import type { JSX } from "react";
import { deploymentsCsvBlob } from "./deploymentCsv";
import type { DeploymentRow } from "./client";

export type DeploymentsCsvExportProps = {
  deployments: ReadonlyArray<DeploymentRow>;
};

function utcTimestamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

export function DeploymentsCsvExport({
  deployments,
}: DeploymentsCsvExportProps): JSX.Element {
  const handleExport = (): void => {
    const blob = deploymentsCsvBlob(deployments);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `krellbot-deployments-${utcTimestamp()}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  };

  return (
    <button
      type="button"
      data-testid="ops-deployments-csv-export"
      disabled={deployments.length === 0}
      onClick={handleExport}
    >
      Export deployments
    </button>
  );
}
