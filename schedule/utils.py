import datetime
import heapq
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponseRedirect
from django.conf import settings
from schedule.conf.settings import CHECK_PERMISSION_FUNC
import re
from django.template.defaultfilters import slugify

class EventListManager(object):
    """
    This class is responsible for doing functions on a list of events. It is
    used to when one has a list of events and wants to access the occurrences
    from these events in as a group
    """
    def __init__(self, events):
        self.events = events

    def occurrences_after(self, after=None):
        """
        It is often useful to know what the next occurrence is given a list of
        events.  This function produces a generator that yields the
        the most recent occurrence after the date ``after`` from any of the
        events in ``self.events``
        """
        from schedule.models import Occurrence
        if after is None:
            after = datetime.datetime.now()
        occ_replacer = OccurrenceReplacer(
            Occurrence.objects.filter(event__in = self.events))
        generators = [event._occurrences_after_generator(after) for event in self.events]
        occurrences = []

        for generator in generators:
            try:
                heapq.heappush(occurrences, (generator.next(), generator))
            except StopIteration:
                pass

        while True:
            if len(occurrences) == 0: raise StopIteration

            generator=occurrences[0][1]

            try:
                next = heapq.heapreplace(occurrences, (generator.next(), generator))[0]
            except StopIteration:
                next = heapq.heappop(occurrences)[0]
            yield occ_replacer.get_occurrence(next)


class OccurrenceReplacer(object):
    """
    When getting a list of occurrences, the last thing that needs to be done
    before passing it forward is to make sure all of the occurrences that
    have been stored in the datebase replace, in the list you are returning,
    the generated ones that are equivalent.  This class makes this easier.
    """
    def __init__(self, persisted_occurrences):
        lookup = [((occ.event, occ.original_start, occ.original_end), occ) for
            occ in persisted_occurrences]
        self.lookup = dict(lookup)

    def get_occurrence(self, occ):
        """
        Return a persisted occurrences matching the occ and remove it from lookup since it
        has already been matched
        """
        return self.lookup.pop(
            (occ.event, occ.original_start, occ.original_end),
            occ)

    def has_occurrence(self, occ):
        return (occ.event, occ.original_start, occ.original_end) in self.lookup

    def get_additional_occurrences(self, start, end):
        """
        Return persisted occurrences which are now in the period
        """
        return [occ for key,occ in self.lookup.items() if (occ.start < end and occ.end >= start and not occ.cancelled)]


class check_event_permissions(object):

    def __init__(self, f):
        self.f = f
        self.contenttype = ContentType.objects.get(app_label='schedule', model='event')

    def __call__(self, request, *args, **kwargs):
        user = request.user
        object_id = kwargs.get('event_id', None)
        try:
            obj = self.contenttype.get_object_for_this_type(pk=object_id)
        except self.contenttype.model_class().DoesNotExist:
            obj = None
        allowed = CHECK_PERMISSION_FUNC(obj, user)
        if not allowed:
            return HttpResponseRedirect(settings.LOGIN_URL)
        return self.f(request, *args, **kwargs)


def coerce_date_dict(date_dict):
    """
    given a dictionary (presumed to be from request.GET) it returns a tuple
    that represents a date. It will return from year down to seconds until one
    is not found.  ie if year, month, and seconds are in the dictionary, only
    year and month will be returned, the rest will be returned as min. If none
    of the parts are found return an empty tuple.
    """
    keys = ['year', 'month', 'day', 'hour', 'minute', 'second']
    retVal = {
                'year': 1,
                'month': 1,
                'day': 1,
                'hour': 0,
                'minute': 0,
                'second': 0}
    modified = False
    for key in keys:
        try:
            retVal[key] = int(date_dict[key])
            modified = True
        except KeyError:
            break
    return modified and retVal or {}


def unique_slugify(instance, value, slug_field_name='slug', queryset=None,
                   slug_separator='-'):
    """
    Calculates and stores a unique slug of ``value`` for an instance.

    ``slug_field_name`` should be a string matching the name of the field to
    store the slug in (and the field to check against for uniqueness).

    ``queryset`` usually doesn't need to be explicitly provided - it'll default
    to using the ``.all()`` queryset from the model's default manager.
    """
    slug_field = instance._meta.get_field(slug_field_name)

    slug = getattr(instance, slug_field.attname)
    slug_len = slug_field.max_length

    # Sort out the initial slug, limiting its length if necessary.
    slug = slugify(value)
    if slug_len:
        slug = slug[:slug_len]
    slug = _slug_strip(slug, slug_separator)
    original_slug = slug

    # Create the queryset if one wasn't explicitly provided and exclude the
    # current instance from the queryset.
    if queryset is None:
        queryset = instance.__class__._default_manager.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    # Find a unique slug. If one matches, at '-2' to the end and try again
    # (then '-3', etc).
    next = 2
    while not slug or queryset.filter(**{slug_field_name: slug}):
        slug = original_slug
        end = '%s%s' % (slug_separator, next)
        if slug_len and len(slug) + len(end) > slug_len:
            slug = slug[:slug_len-len(end)]
            slug = _slug_strip(slug, slug_separator)
        slug = '%s%s' % (slug, end)
        next += 1

    setattr(instance, slug_field.attname, slug)


def _slug_strip(value, separator='-'):
    """
    Cleans up a slug by removing slug separator characters that occur at the
    beginning or end of a slug.

    If an alternate separator is used, it will also replace any instances of
    the default '-' separator with the new separator.
    """
    separator = separator or ''
    if separator == '-' or not separator:
        re_sep = '-'
    else:
        re_sep = '(?:-|%s)' % re.escape(separator)
        # Remove multiple instances and if an alternate separator is provided,
    # replace the default '-' separator.
    if separator != re_sep:
        value = re.sub('%s+' % re_sep, separator, value)
        # Remove separator from the beginning and end of the slug.
    if separator:
        if separator != '-':
            re_sep = re.escape(separator)
        value = re.sub(r'^%s+|%s+$' % (re_sep, re_sep), '', value)
    return value