import { useCallback, useState } from "react";
import { errorMessage } from "../api/client";
import { monitoring } from "../api/endpoints";
import { useToast } from "../components/Toast";
import { useTranslation } from "react-i18next";

/**
 * start / stop / restart for one camera's stream worker.
 *
 * `busyId` is the camera currently mid-action rather than a plain boolean, so
 * a list of exits can disable just the row being acted on instead of freezing
 * the whole page.
 */
export function useMonitoringActions(onDone) {
  const { t } = useTranslation();
  const toast = useToast();
  const [busyId, setBusyId] = useState(null);

  const run = useCallback(
    async (action, cameraId) => {
      setBusyId(cameraId);
      try {
        const result = await monitoring[action](cameraId);
        toast.success(result?.message || t(`useMonitoringActions.done_${action}`));
        await onDone?.();
        return result;
      } catch (error) {
        toast.error(errorMessage(error));
        return null;
      } finally {
        setBusyId(null);
      }
    },
    [onDone, toast, t]
  );

  return {
    busyId,
    start: (id) => run("start", id),
    stop: (id) => run("stop", id),
    restart: (id) => run("restart", id),
  };
}

export default useMonitoringActions;
