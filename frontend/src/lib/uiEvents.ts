/**
 * Small window-level event bus for cross-component UI refresh.
 *
 * The notification bell lives in the application shell and the notification
 * centre is a page; both read the same rows. Without a signal, marking a
 * message read in one leaves the other showing a stale unread count until its
 * next poll. Both sides now announce and listen to one named event, so the
 * number in the header always matches the list the user just changed.
 */
const NOTIFICATIONS_CHANGED = 'notifications-changed'

export function notifyNotificationsChanged(): void {
  window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED))
}

export function onNotificationsChanged(handler: () => void): () => void {
  window.addEventListener(NOTIFICATIONS_CHANGED, handler)
  return () => window.removeEventListener(NOTIFICATIONS_CHANGED, handler)
}
