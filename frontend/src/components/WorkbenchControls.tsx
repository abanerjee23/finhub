export type SweepProgress = {
  processed: number;
  total: number;
} | null;

export function WorkbenchControls({
  queuePending,
  seedCount,
  sweepBatchSize,
  busy,
  apiOnline,
  sweepProgress,
  onSeedCountChange,
  onSweepBatchSizeChange,
  onReset,
  onSweep,
  onRefresh
}: {
  queuePending: number;
  seedCount: number;
  sweepBatchSize: number;
  busy: boolean;
  apiOnline: boolean | null;
  sweepProgress: SweepProgress;
  onSeedCountChange: (value: number) => void;
  onSweepBatchSizeChange: (value: number) => void;
  onReset: () => void;
  onSweep: () => void;
  onRefresh: () => void;
}) {
  return (
    <section className="panel workbench-panel">
      <div className="panel-header">
        <h2>Workbench Controls</h2>
        <span>
          {queuePending} document{queuePending === 1 ? "" : "s"} waiting in queue
        </span>
      </div>
      <div className="workbench-controls">
        <label htmlFor="seed-count">
          Seed count
          <input
            id="seed-count"
            min={1}
            max={500}
            type="number"
            value={seedCount}
            onChange={(event) => onSeedCountChange(Number(event.target.value) || 50)}
            disabled={busy}
          />
        </label>
        <button
          className="secondary"
          disabled={busy || apiOnline === false}
          onClick={onReset}
          type="button"
        >
          Reset &amp; seed queue
        </button>
        <label htmlFor="sweep-batch">
          Batch size
          <input
            id="sweep-batch"
            min={1}
            max={25}
            type="number"
            value={sweepBatchSize}
            onChange={(event) => onSweepBatchSizeChange(Number(event.target.value) || 5)}
            disabled={busy}
          />
        </label>
        <button
          disabled={busy || apiOnline === false || queuePending === 0}
          onClick={onSweep}
          type="button"
        >
          {busy ? "Processing…" : "Run agent processing"}
        </button>
        <button
          className="secondary"
          disabled={busy || apiOnline === false}
          onClick={onRefresh}
          type="button"
        >
          Refresh
        </button>
      </div>
      {sweepProgress ? (
        <div className="sweep-progress">
          <div className="sweep-progress-track">
            <div
              className="sweep-progress-fill"
              style={{
                width: sweepProgress.total
                  ? `${Math.round((sweepProgress.processed / sweepProgress.total) * 100)}%`
                  : "10%"
              }}
            />
          </div>
          <span>
            Agents processing {sweepProgress.processed}/{sweepProgress.total} documents…
          </span>
        </div>
      ) : null}
    </section>
  );
}
